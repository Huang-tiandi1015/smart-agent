"""里程碑 3 端到端测试：Claude API 意图解析（AI 规划器）。

验证 LLM 路径把自然语言指令映射到工具调用，且审批/执行/回退机制不变：
  场景A LLM 路由：自然语言变体「把桌面上的图片和文档按类型整理一下」
        -> 弹审批 -> 批准 -> done -> 验证文件移入 图片/ 文档/
  场景B 超能力指令：「帮我发一封邮件」-> done + 非空 reply
        （LLM 文本说明或回退规则文案，不误调工具、不崩溃）

需在 .env 填好 ANTHROPIC_API_KEY 后运行（服务端以 auto 模式启动）。
复用 milestone2_demo 的 DemoClient / check / make_files / get_token。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

import websockets

# 复用里程碑 2 测试脚本的公共组件
sys.path.insert(0, str(Path(__file__).resolve().parent))
import milestone2_demo as m2  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DemoClient, check, get_token, make_files = m2.DemoClient, m2.check, m2.get_token, m2.make_files


async def run_demo(host: str, port: int, code: str, sandbox: Path) -> None:
    base = f"http://{host}:{port}"
    device_id = uuid.uuid4().hex[:12]
    desktop = sandbox / "desktop"

    data = get_token(base, code, device_id)
    print(f"[配对] device_id={data['device_id']} expires_in={data['expires_in']}s")

    uri = f"ws://{host}:{port}/ws"
    async with websockets.connect(uri) as ws:
        client = DemoClient(ws)
        await client.send({"type": "auth", "token": data["token"]})
        await client.wait_for("authed")
        print("[连接] WS 认证成功")

        # ---------- 场景A：LLM 路由到 organize_desktop ----------
        print("\n场景A LLM 路由：自然语言指令 -> 审批 -> 批准 -> 归档")
        make_files(desktop, ["photo1.png", "report.docx"])
        job_id = await client.send_command("把桌面上的图片和文档按类型整理一下")
        req = await client.wait_for("approval_request")
        check(req["job_id"] == job_id, "自然语言指令触发了审批请求")
        # LLM 路由到 organize_desktop：审批明细应包含待归档文件（图片+文档）
        check("photo1.png" in "".join(req.get("details", [])), "审批明细含图片文件（LLM 正确路由到整理工具）")
        check("report.docx" in "".join(req.get("details", [])), "审批明细含文档文件")
        await client.send(
            {"type": "approval_response", "job_id": job_id, "decision": "approve", "trust": "once"}
        )
        term = await client.wait_terminal(job_id)
        check(term["status"] == "done", f"任务终态 status={term['status']}")
        check((desktop / "图片" / "photo1.png").exists(), "photo1.png 已移入 图片/")
        check((desktop / "文档" / "report.docx").exists(), "report.docx 已移入 文档/")

        # ---------- 场景B：超能力指令（无工具可做） ----------
        print("\n场景B 超能力指令：帮我发一封邮件 -> done + 非空回复（不误调工具）")
        job_id = await client.send_command("帮我发一封邮件")
        term = await client.wait_terminal(job_id)
        check(term["status"] == "done", f"任务终态 status={term['status']}")
        reply = (term.get("result") or {}).get("reply", "")
        check(bool(reply), f"返回非空提示: {reply!r}")
        check(term.get("tool_name") is None, "未绑定任何工具（无工具被调用）")

        await client.close()

    print(f"\n全部 {m2.CHECKS} 项断言通过 —— 里程碑 3（LLM 规划器）端到端验证 OK")


def main() -> None:
    parser = argparse.ArgumentParser(description="里程碑 3 端到端测试（LLM 意图解析）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--code", required=True, help="服务端控制台打印的 6 位配对码")
    parser.add_argument("--sandbox", required=True, help="沙箱根目录（含 desktop/）")
    args = parser.parse_args()
    asyncio.run(run_demo(args.host, args.port, args.code, Path(args.sandbox)))


if __name__ == "__main__":
    main()
