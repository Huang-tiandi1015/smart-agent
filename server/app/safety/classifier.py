"""执行前安全检查：目录黑名单硬拦截。

里程碑 4：即使手机端批准，命中黑名单的工具调用也直接拒绝执行
（例如「整理 C:\\Windows」）。黑名单为前缀匹配 + 盘符根目录规则，
只读判定，不做任何实际改动。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Windows 系统/关键目录，禁止作为整理目标
BLOCKED_PATH_PREFIXES = (
    "c:\\windows",
    "c:\\program files (x86)",
    "c:\\program files",
    "c:\\programdata",
    "c:\\$recycle.bin",
    "c:\\system volume information",
    "c:\\recovery",
    "c:\\users\\public",
)

# 盘符根目录（整理整个盘过于危险）
DRIVE_ROOT_RE = re.compile(r"^[a-zA-Z]:[\\/]*$")

# 判定为「疑似路径」：含路径分隔符或盘符前缀
_PATH_LIKE_RE = re.compile(r"(^[a-zA-Z]:[\\/])|[\\/]")


@dataclass
class SafetyDecision:
    allowed: bool
    reason: str | None = None


def check_directory(path: str) -> str | None:
    """检查一个目录路径是否命中黑名单；命中返回理由，否则返回 None。"""
    p = (path or "").strip().lower()
    if not p:
        return None
    for prefix in BLOCKED_PATH_PREFIXES:
        if p.startswith(prefix):
            return f"目录命中黑名单前缀: {prefix}"
    if DRIVE_ROOT_RE.match(p):
        return "不允许整理盘符根目录"
    return None


def check_tool(tool, args: dict) -> SafetyDecision:
    """检查工具调用的参数中是否含黑名单路径。命中即拒绝。"""
    for key, value in (args or {}).items():
        if not isinstance(value, str) or not _PATH_LIKE_RE.search(value):
            continue
        reason = check_directory(value)
        if reason:
            return SafetyDecision(allowed=False, reason=f"{key} 字段: {reason}")
    return SafetyDecision(allowed=True)
