"""端到端冒烟测试客户端：配对 -> WS 认证 -> echo 往返 + 心跳应答。

用法：
    .venv/Scripts/python scripts/client_demo.py --code <配对码> [--host 127.0.0.1] [--port 8000]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import urllib.error
import urllib.request
import uuid

import websockets


def get_token(base_url: str, code: str, device_id: str) -> dict:
    payload = json.dumps({"code": code, "device_id": device_id}).encode("utf-8")
    req = urllib.request.Request(
        base_url + "/api/pair",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"配对失败: HTTP {e.code} {e.read().decode()}") from e


async def main() -> None:
    parser = argparse.ArgumentParser(description="Smart Agent 通信链路冒烟测试")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--code", required=True, help="服务端控制台打印的 6 位配对码")
    parser.add_argument("--echo", default="你好，电脑！链路已跑通")
    args = parser.parse_args()

    base = f"http://{args.host}:{args.port}"
    device_id = uuid.uuid4().hex[:12]

    # 1. 配对
    data = get_token(base, args.code, device_id)
    print(f"[1] 配对成功 device_id={data['device_id']} expires_in={data['expires_in']}s")

    # 2. 连接 WS 并认证，3. 发 echo，同时应答服务端心跳
    uri = f"ws://{args.host}:{args.port}/ws"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "auth", "token": data["token"]}))
        await ws.send(json.dumps({"type": "echo", "text": args.echo}))
        print(f"[2] 已连接，发送 echo: {args.echo}")

        deadline = time.time() + 20
        got_echo = False
        got_ping = False
        while time.time() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            if msg["type"] == "authed":
                print(f"[3] 认证成功 device_id={msg['device_id']}")
            elif msg["type"] == "echo_reply":
                print(f"[4] 收到回复: {msg['text']}  ts={msg['ts']}")
                got_echo = True
            elif msg["type"] == "ping":
                await ws.send(json.dumps({"type": "pong"}))
                got_ping = True
            if got_echo and got_ping:
                break
        else:
            raise SystemExit("超时：未收到 echo 回复")

        print("[5] 链路验证通过（echo 往返 + 心跳应答）")


if __name__ == "__main__":
    asyncio.run(main())
