"""里程碑 4 端到端测试：黑名单硬拦截 + 任务取消 + recent 历史拉取。

用法（沙箱模式，避免动真实桌面）：
    1. 建沙箱目录：mkdir -p .sandbox_demo/desktop
    2. 用沙箱桌面启动服务（另开终端）：
       SMART_AGENT_DESKTOP_DIR="D:/Claude Code/smart-agent/.sandbox_demo/desktop" \\
         .venv/Scripts/python -m uvicorn server.app.main:app --host 0.0.0.0 --port 8000
    3. 另开终端，从服务端控制台取 6 位配对码后运行：
       .venv/Scripts/python scripts/milestone4_demo.py --code <配对码> \\
         --sandbox "D:/Claude Code/smart-agent/.sandbox_demo"

三场景：
  场景1 黑名单：整理 C:\\Windows -> failed（error 含「安全拦截」，不执行、不弹审批）
  场景2 取消：发敏感指令 -> 弹审批 -> 发 cancel -> cancelled
  场景3 recent：发 get_recent -> 收到 recent，列表非空且含本会话 job_id
"""
from __future__ import annotations

import argparse
import asyncio
import time
import uuid
from pathlib import Path

import websockets

import milestone2_demo as m2  # 复用 DemoClient / check / get_token / CHECKS


async def wait_cancelled(client: m2.DemoClient, job_id: str, timeout: float = 15) -> dict:
    """等待任务进入 cancelled 终态。"""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"等待任务 {job_id} cancelled 超时")
        msg = await client.wait_for("job_status", remaining)
        if msg["job_id"] == job_id and msg["status"] == "cancelled":
            return msg


async def run_demo(host: str, port: int, code: str, sandbox: Path) -> None:
    base = f"http://{host}:{port}"
    device_id = uuid.uuid4().hex[:12]
    desktop = sandbox / "desktop"

    data = m2.get_token(base, code, device_id)
    print(f"[配对] device_id={data['device_id']} expires_in={data['expires_in']}s")

    uri = f"ws://{host}:{port}/ws"
    async with websockets.connect(uri) as ws:
        client = m2.DemoClient(ws)
        await client.send({"type": "auth", "token": data["token"]})
        await client.wait_for("authed")
        print("[连接] WS 认证成功")

        # ---------- 场景1：黑名单硬拦截 ----------
        print("\n场景1 黑名单：整理 C:\\Windows -> failed（安全拦截，不执行）")
        job_id = await client.send_command("整理 C:\\Windows")
        term = await client.wait_terminal(job_id)
        m2.check(term["status"] == "failed", f"任务终态 status={term['status']}")
        m2.check("安全拦截" in (term.get("error") or ""), f"error 含「安全拦截」: {term.get('error')!r}")
        m2.check(not (term.get("result") or {}).get("moved"), "未执行任何移动")

        # ---------- 场景2：取消 ----------
        print("\n场景2 取消：整理沙箱桌面 -> 弹审批 -> 发 cancel -> cancelled")
        m2.make_files(desktop, ["todo.txt"])
        job_id = await client.send_command(f"整理 {desktop}")
        req = await client.wait_for("approval_request")
        m2.check(req["job_id"] == job_id, f"收到审批请求 job_id={job_id}")
        await client.send({"type": "cancel", "job_id": job_id})
        term = await wait_cancelled(client, job_id)
        m2.check(term["status"] == "cancelled", f"任务终态 status={term['status']}")
        m2.check((desktop / "todo.txt").exists(), "文件未被移动")

        # ---------- 场景3：recent 历史拉取 ----------
        print("\n场景3 recent：发 get_recent -> 收到 recent，含本会话 job_id")
        await client.send({"type": "get_recent"})
        msg = await client.wait_for("recent")
        jobs = msg.get("jobs", [])
        m2.check(len(jobs) >= 2, f"recent 列表非空（{len(jobs)} 条）")
        ids = [j["job_id"] for j in jobs]
        m2.check(job_id in ids, "recent 含本会话取消任务的 job_id")
        canceled = next((j for j in jobs if j["job_id"] == job_id), None)
        m2.check(canceled and canceled["status"] == "cancelled", "recent 中该任务状态为 cancelled")

        await client.close()

    print(f"\n全部 {m2.CHECKS} 项断言通过 —— 里程碑 4 端到端验证 OK")


def main() -> None:
    parser = argparse.ArgumentParser(description="里程碑 4 端到端测试（黑名单/取消/recent）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--code", required=True, help="服务端控制台打印的 6 位配对码")
    parser.add_argument("--sandbox", required=True, help="沙箱根目录（含 desktop/）")
    args = parser.parse_args()
    asyncio.run(run_demo(args.host, args.port, args.code, Path(args.sandbox)))


if __name__ == "__main__":
    main()
