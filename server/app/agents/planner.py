"""指令解析：把手机端自然语言指令映射为具体工具调用。

里程碑 2 用关键词规则；里程碑 3 引入 LLM 意图解析（OpenAI 兼容端点，默认 DeepSeek）
作为主路径，plan_command 作为门面（异步）：优先走 LLM，不可用/失败回退 rules_plan。
上层（jobs.py）只需 await planner.plan_command(text)，接口保持稳定。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import config

_PATH_SEP_RE = re.compile(r"[\\/:]")

# 支持的一字指令（帮助）
_COMMANDS = [
    "整理桌面文件 —— 把桌面按类型归档（需手机确认）",
    "整理 <目录路径> —— 归档指定目录",
    "打开 <软件名> —— 启动已安装的软件，如 Steam、微信（需手机确认）",
]


@dataclass
class PlanResult:
    tool_name: str | None = None
    args: dict = field(default_factory=dict)
    reply: str | None = None  # 非工具类回复（帮助/提示）
    is_help: bool = False


async def plan_command(text: str) -> PlanResult:
    """门面：优先走 LLM 意图解析；不可用/失败回退关键词规则。

    - PLANNER_MODE=rules 或未配置 API key -> 直接走规则引擎
    - LLM 返回 None（SDK 缺失/网络/超时/非法响应）-> 回退规则引擎
    """
    if config.PLANNER_MODE == "rules" or not config.DEEPSEEK_API_KEY:
        return rules_plan(text)
    from .llm_planner import plan_with_llm  # 惰性导入，避免与 llm_planner 循环依赖

    plan = await plan_with_llm(text)
    return plan if plan is not None else rules_plan(text)


def rules_plan(text: str) -> PlanResult:
    """关键词规则引擎（里程碑 2 逻辑，作为 LLM 不可用时的回退）。"""
    t = text.strip()
    low = t.lower()

    # 帮助
    if any(k in low for k in ("help", "帮助", "能做什么", "支持什么", "指令")):
        return PlanResult(is_help=True, reply="支持的指令：\n" + "\n".join(f"· {c}" for c in _COMMANDS))

    # 整理 <路径>：优先提取显式路径（避免路径中含 "desktop" 子串被误判为整理桌面）
    if "整理" in text or "归类" in text or "organize" in low:
        directory = _extract_dir(t)
        if directory:
            return PlanResult(tool_name="organize_desktop", args={"directory": directory})
        if "桌面" in text or "desktop" in low:
            return PlanResult(tool_name="organize_desktop", args={"directory": config.DESKTOP_DIR})

    # 打开/启动 <软件>：仅处理「打开X / X打开」这类短指令，长句交给 LLM
    app = _extract_open_app(t)
    if app:
        return PlanResult(tool_name="launch_app", args={"app": app})

    return PlanResult(reply="未识别的指令。发送「帮助」查看支持的命令。")


def _extract_dir(text: str) -> str | None:
    """提取「整理 <路径>」中的路径；支持带空格的 Windows 路径。"""
    t = text.strip()
    for verb in ("整理", "归类"):
        if t.startswith(verb):
            t = t[len(verb):].lstrip(" :：").strip()
            break
    else:
        if not t.lower().startswith("organize"):
            return None
        t = t[len("organize"):].lstrip(" :：").strip()
    if not t:
        return None
    t = t.rstrip("，。；,;！!？?")
    return t if _PATH_SEP_RE.search(t) else None


def _extract_open_app(text: str) -> str | None:
    """提取「打开 <软件名>」或「<软件名> 打开」中的软件名；其余形式返回 None。"""
    t = text.strip().strip("，。；,;！!？? ")
    for kw in ("打开", "启动"):
        if t.startswith(kw):
            return t[len(kw):].strip(" ：:，。；,;！!？?").strip() or None
        if t.endswith(kw):
            return t[:-len(kw)].strip(" ：:，。；,;！!？?").strip() or None
    return None
