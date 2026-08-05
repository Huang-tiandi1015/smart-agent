"""WebSocket 端点：认证 -> 心跳 -> 消息路由。

处理：echo（连通性）、command（远程指令 -> JobManager）、
approval_response（审批决定）、心跳。
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from shared import protocol as p

from ..core.auth import AuthManager
from ..core.hub import ConnectionHub
from ..core.jobs import JobManager

logger = logging.getLogger("smart-agent.ws")
router = APIRouter()

AUTH_TIMEOUT = 10  # 等待首条 auth 消息的超时（秒）


def init_ws(
    auth: AuthManager,
    hub: ConnectionHub,
    heartbeat_interval: float,
    heartbeat_timeout: float,
    job_manager: JobManager,
) -> APIRouter:
    @router.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        device_id: str | None = None
        try:
            device_id = await _authenticate(ws, auth)
            if device_id is None:
                return
            hub.add(device_id, ws)
            await ws.send_json(p.make_message(p.MSG_AUTHED, device_id=device_id))
            await _message_loop(ws, hub, device_id, heartbeat_interval, heartbeat_timeout, job_manager)
        except WebSocketDisconnect:
            pass
        finally:
            if device_id:
                hub.remove(device_id, ws)

    return router


async def _authenticate(ws: WebSocket, auth: AuthManager) -> str | None:
    """要求首条消息为 auth 并校验 token；返回 device_id，失败返回 None。"""
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=AUTH_TIMEOUT)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await ws.close(code=1008)
        return None
    try:
        msg = p.loads(raw)
    except ValueError:
        await ws.close(code=1008)
        return None
    if msg.get("type") != p.MSG_AUTH:
        await ws.send_json(p.make_message(p.MSG_ERROR, code="unauthenticated", message="首条消息必须是 auth"))
        await ws.close(code=1008)
        return None
    token = auth.validate(msg.get("token", ""))
    if token is None:
        await ws.send_json(p.make_message(p.MSG_ERROR, code="unauthorized", message="token 无效"))
        await ws.close(code=1008)
        return None
    return token.device_id


async def _message_loop(
    ws: WebSocket,
    hub: ConnectionHub,
    device_id: str,
    heartbeat_interval: float,
    heartbeat_timeout: float,
    job_manager: JobManager,
) -> None:
    state = {"last_pong": time.monotonic()}
    stop = asyncio.Event()

    async def heartbeat() -> None:
        while not stop.is_set():
            await asyncio.sleep(heartbeat_interval)
            if time.monotonic() - state["last_pong"] > heartbeat_timeout:
                logger.info("device %s heartbeat timeout, closing", device_id)
                await ws.close(code=1000)
                return
            try:
                await ws.send_json(p.make_message(p.MSG_PING, ts=time.time()))
            except Exception:
                return

    hb_task = asyncio.create_task(heartbeat())
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = p.loads(raw)
            except ValueError:
                await ws.send_json(p.make_message(p.MSG_ERROR, code="bad_message", message="非法 JSON"))
                continue
            await _handle_message(ws, msg, state, device_id, job_manager)
    finally:
        stop.set()
        hb_task.cancel()


async def _handle_message(
    ws: WebSocket,
    msg: dict,
    state: dict,
    device_id: str,
    job_manager: JobManager,
) -> None:
    mtype = msg.get("type")
    if mtype == p.MSG_ECHO:
        await ws.send_json(p.make_message(p.MSG_ECHO_REPLY, text=msg.get("text", ""), ts=time.time()))
    elif mtype == p.MSG_PONG:
        state["last_pong"] = time.monotonic()
    elif mtype == p.MSG_COMMAND:
        text = (msg.get("text") or "").strip()
        if not text:
            await ws.send_json(p.make_message(p.MSG_ERROR, code="empty_command", message="指令为空"))
            return
        await job_manager.submit(device_id, text)  # 状态推送由 JobManager 负责
    elif mtype == p.MSG_APPROVAL_RESPONSE:
        ok = await job_manager.handle_approval(
            device_id,
            str(msg.get("job_id", "")),
            str(msg.get("decision", "")),
            str(msg.get("trust", "once")),
        )
        if not ok:
            await ws.send_json(p.make_message(p.MSG_ERROR, code="bad_approval", message="审批响应无效或任务不在审批中"))
    else:
        await ws.send_json(p.make_message(p.MSG_ERROR, code="unknown_type", message=f"未知消息类型: {mtype}"))
