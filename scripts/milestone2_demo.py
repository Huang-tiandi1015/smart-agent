"""里程碑 2 端到端测试：指令执行 + 审批机制 + 工具归档 + 1h 信任。

用法（沙箱模式，避免动真实桌面）：
    1. 建沙箱目录：
       mkdir -p .sandbox_demo/desktop .sandbox_demo/desktop2
    2. 用沙箱桌面启动服务（另开终端）：
       SMART_AGENT_DESKTOP_DIR="D:/Claude Code/smart-agent/.sandbox_demo/desktop" \\
         .venv/Scripts/python -m uvicorn server.app.main:app --host 0.0.0.0 --port 8000
    3. 另开终端，从服务端控制台取 6 位配对码后运行：
       .venv/Scripts/python scripts/milestone2_demo.py --code <配对码> \\
         --sandbox "D:/Claude Code/smart-agent/.sandbox_demo"

四场景：
  场景1 批准：整理桌面文件 -> 审批批准 -> done -> 验证文件已归档
  场景2 拒绝：整理 <desktop2> -> 拒绝 -> rejected -> 验证文件未动
  场景3 未知指令：打开浏览器 -> done（返回提示，不执行任何工具）
  场景4 1h 信任：批准(1h) 后再次发同指令 -> 不再弹审批，直接执行
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import websockets

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    mark = "PASS" if cond else "FAIL"
    print(f"    [{mark}] {label}")
    if not cond:
        raise SystemExit(f"断言失败: {label}")


def get_token(base_url: str, code: str, device_id: str) -> dict:
    payload = json.dumps({"code": code, "device_id": device_id}).encode("utf-8")
    req = urllib.request.Request(
        base_url + "/api/pair", data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"配对失败: HTTP {e.code} {e.read().decode()}") from e


class DemoClient:
    """封装 WS：后台读取消息进队列，自动应答心跳。"""

    def __init__(self, ws) -> None:
        self.ws = ws
        self._events: asyncio.Queue[dict] = asyncio.Queue()
        self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            while True:
                raw = await self.ws.recv()
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await self.ws.send(json.dumps({"type": "pong"}))
                    continue
                await self._events.put(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async def next_event(self, timeout: float = 15) -> dict:
        return await asyncio.wait_for(self._events.get(), timeout)

    async def wait_for(self, mtype: str, timeout: float = 15) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"等待 {mtype} 超时")
            msg = await self.next_event(remaining)
            if msg.get("type") == mtype:
                return msg

    async def send(self, msg: dict) -> None:
        await self.ws.send(json.dumps(msg, ensure_ascii=False))

    async def send_command(self, text: str) -> str:
        """发送指令并等待任务创建，返回 job_id。"""
        await self.send({"type": "command", "text": text})
        while True:
            msg = await self.wait_for("job_status")
            if msg["status"] == "created":
                return msg["job_id"]

    async def wait_terminal(self, job_id: str, timeout: float = 15) -> dict:
        """等待任务的终态（done/failed/rejected）。"""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"等待任务 {job_id} 终态超时")
            msg = await self.wait_for("job_status", remaining)
            if msg["job_id"] != job_id:
                continue
            if msg["status"] in ("done", "failed", "rejected"):
                return msg

    async def wait_terminal_no_approval(self, job_id: str, timeout: float = 15) -> dict:
        """等待终态；期间出现审批请求/等待审批即视为失败（用于验证 1h 信任）。"""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"任务 {job_id} 未在免审批下完成")
            msg = await self.next_event(remaining)
            if msg.get("type") == "approval_request" and msg.get("job_id") == job_id:
                raise AssertionError("不应弹出审批请求（1h 信任应生效）")
            if msg.get("type") != "job_status" or msg.get("job_id") != job_id:
                continue
            if msg["status"] == "awaiting_approval":
                raise AssertionError("任务进入了审批等待（1h 信任应生效）")
            if msg["status"] in ("done", "failed", "rejected"):
                return msg

    async def close(self) -> None:
        self._reader.cancel()
        await self.ws.close()


def make_files(directory: Path, names: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("demo", encoding="utf-8")


async def run_demo(host: str, port: int, code: str, sandbox: Path) -> None:
    base = f"http://{host}:{port}"
    device_id = uuid.uuid4().hex[:12]
    desktop = sandbox / "desktop"
    desktop2 = sandbox / "desktop2"

    data = get_token(base, code, device_id)
    print(f"[配对] device_id={data['device_id']} expires_in={data['expires_in']}s")

    uri = f"ws://{host}:{port}/ws"
    async with websockets.connect(uri) as ws:
        client = DemoClient(ws)
        await client.send({"type": "auth", "token": data["token"]})
        await client.wait_for("authed")
        print("[连接] WS 认证成功")

        # ---------- 场景1：批准 ----------
        print("\n场景1 批准：整理桌面文件 -> 批准 -> done -> 文件已归档")
        make_files(desktop, ["photo1.png", "note.txt"])
        job_id = await client.send_command("整理桌面文件")
        req = await client.wait_for("approval_request")
        check(req["job_id"] == job_id, f"收到审批请求 job_id={job_id}")
        check("photo1.png" in "".join(req.get("details", [])), "审批明细含待归档文件")
        await client.send(
            {"type": "approval_response", "job_id": job_id, "decision": "approve", "trust": "once"}
        )
        term = await client.wait_terminal(job_id)
        check(term["status"] == "done", f"任务终态 status={term['status']}")
        check((desktop / "图片" / "photo1.png").exists(), "photo1.png 已移入 图片/")
        check((desktop / "文档" / "note.txt").exists(), "note.txt 已移入 文档/")
        check(not (desktop / "photo1.png").exists(), "photo1.png 原位置已清空")

        # ---------- 场景2：拒绝 ----------
        print("\n场景2 拒绝：整理 desktop2 -> 拒绝 -> rejected -> 文件未动")
        make_files(desktop2, ["keep.txt"])
        job_id = await client.send_command(f"整理 {desktop2}")
        req = await client.wait_for("approval_request")
        check(req["job_id"] == job_id, f"收到审批请求 job_id={job_id}")
        await client.send({"type": "approval_response", "job_id": job_id, "decision": "deny"})
        term = await client.wait_terminal(job_id)
        check(term["status"] == "rejected", f"任务终态 status={term['status']}")
        check((desktop2 / "keep.txt").exists(), "keep.txt 未被移动")

        # ---------- 场景3：未知指令 ----------
        print("\n场景3 未知指令：打开浏览器 -> done（返回提示，不执行工具）")
        job_id = await client.send_command("打开浏览器")
        term = await client.wait_terminal(job_id)
        check(term["status"] == "done", f"任务终态 status={term['status']}")
        reply = (term.get("result") or {}).get("reply", "")
        # 规则路径返回「未识别的指令…」，LLM 路径返回自然语言提示；两条路径都应给出非空回复
        check(bool(reply), f"返回提示回复: {reply!r}")

        # ---------- 场景4：1h 信任 ----------
        print("\n场景4 1h 信任：批准(1h) 后再次发同指令 -> 不再弹审批，直接执行")
        make_files(desktop, ["again.docx"])
        job_id = await client.send_command("整理桌面文件")
        req = await client.wait_for("approval_request")
        await client.send(
            {"type": "approval_response", "job_id": job_id, "decision": "approve", "trust": "1h"}
        )
        term = await client.wait_terminal(job_id)
        check(term["status"] == "done", f"首次(1h)批准后 status={term['status']}")
        check((desktop / "文档" / "again.docx").exists(), "again.docx 已移入 文档/")

        make_files(desktop, ["again2.xlsx"])
        job_id = await client.send_command("整理桌面文件")
        term = await client.wait_terminal_no_approval(job_id)
        check(term["status"] == "done", f"免审批直接完成 status={term['status']}")
        check((desktop / "文档" / "again2.xlsx").exists(), "again2.xlsx 已移入 文档/")

        await client.close()

    print(f"\n全部 {CHECKS} 项断言通过 —— 里程碑 2 端到端验证 OK")


def main() -> None:
    parser = argparse.ArgumentParser(description="里程碑 2 端到端测试（指令执行 + 审批）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--code", required=True, help="服务端控制台打印的 6 位配对码")
    parser.add_argument("--sandbox", required=True, help="沙箱根目录（含 desktop/ 与 desktop2/）")
    args = parser.parse_args()
    asyncio.run(run_demo(args.host, args.port, args.code, Path(args.sandbox)))


if __name__ == "__main__":
    main()
