"""规则解析：把手机端自然语言指令映射为具体工具调用。

里程碑 2 用关键词规则；里程碑 3 将替换为 Claude API 意图解析，
本模块保持 plan_command 接口不变，上层无需改动。
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
]


@dataclass
class PlanResult:
    tool_name: str | None = None
    args: dict = field(default_factory=dict)
    reply: str | None = None  # 非工具类回复（帮助/提示）
    is_help: bool = False


def plan_command(text: str) -> PlanResult:
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
