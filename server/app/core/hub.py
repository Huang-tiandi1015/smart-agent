"""连接中心：维护所有已认证的 WebSocket 连接，并向客户端推送消息。

每个设备（device_id）可能持有多个连接（如手机多开页面）。
后续里程碑的任务状态/审批请求都将通过 hub 推送。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("smart-agent.hub")


class ConnectionHub:
    def __init__(self) -> None:
        self._clients: dict[str, set] = {}  # device_id -> set[WebSocket]

    def add(self, device_id: str, ws: Any) -> None:
        self._clients.setdefault(device_id, set()).add(ws)
        logger.info("device %s connected (total %d)", device_id, self.count)

    def remove(self, device_id: str, ws: Any) -> None:
        clients = self._clients.get(device_id)
        if clients:
            clients.discard(ws)
            if not clients:
                del self._clients[device_id]
        logger.info("device %s disconnected (total %d)", device_id, self.count)

    @property
    def count(self) -> int:
        return sum(len(v) for v in self._clients.values())

    async def send_to_device(self, device_id: str, message: dict) -> bool:
        """推送消息到指定设备的所有连接；返回是否至少送达一个。"""
        clients = list(self._clients.get(device_id, set()))
        delivered = False
        for ws in clients:
            try:
                await ws.send_json(message)
                delivered = True
            except Exception:
                logger.warning("send to device %s failed, dropping connection", device_id)
                self.remove(device_id, ws)
        return delivered
