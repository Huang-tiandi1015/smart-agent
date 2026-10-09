"""「打开应用」工具：按名称启动一个已安装的软件。

安全设计：
- 按名称在 开始菜单快捷方式 / 常见安装目录 / PATH 中查找可执行文件；
- 找不到时明确报错，不做任何猜测性启动；
- 标记为 sensitive，执行前必须经手机端审批；
- 快捷方式（.lnk）交给 Windows 解析，可执行文件用 subprocess 启动。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .base import ActionDetail, RiskLevel, Tool, ToolResult

SEARCH_EXTENSIONS = (".lnk", ".exe")
MAX_DEPTH = 4

# 已解析到的软件路径缓存（仅缓存命中结果，避免每次重复扫描整个安装目录）
_RESOLVE_CACHE: dict[str, str] = {}
_CACHE_LIMIT = 512


def _default_search_roots() -> list[Path]:
    """搜索根：开始菜单 + 常见安装目录。"""
    roots: list[Path] = []
    for env in ("APPDATA", "PROGRAMDATA"):
        base = os.getenv(env)
        if base:
            roots.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.getenv(env)
        if base:
            roots.append(Path(base))
    local = os.getenv("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "Programs")
    return roots


def _score(stem: str, key: str) -> int:
    """匹配打分，越小越匹配；-1 表示不匹配。

    优先级：精确 > 前缀 > 词级包含 > 子串。
    """
    stem_l = stem.lower()
    if stem_l == key:
        return 0
    if stem_l.startswith(key):
        return 1
    if any(part == key for part in stem_l.split()):
        return 2
    if key in stem_l:
        return 3
    return -1


def resolve_app(name: str, roots: list[Path] | None = None) -> str:
    """按名称解析软件的可启动目标；找不到抛 ValueError。

    roots 仅供测试注入，为 None 时使用默认搜索根并走命中缓存。
    """
    key = name.strip().lower()
    if not key:
        raise ValueError("未指定要打开的软件名")
    if roots is None:
        cached = _RESOLVE_CACHE.get(key)
        if cached is not None:
            return cached
        roots = _default_search_roots()
    best, best_score = None, -1
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            if dirpath[len(str(root)):].count(os.sep) >= MAX_DEPTH:
                dirnames[:] = []  # 达到深度上限不再深入
            for fn in filenames:
                if not fn.lower().endswith(SEARCH_EXTENSIONS):
                    continue
                sc = _score(Path(fn).stem, key)
                if sc == 0:
                    return str(Path(dirpath) / fn)
                if sc > 0 and (best is None or sc < best_score):
                    best, best_score = str(Path(dirpath) / fn), sc
    if best is None:
        found = shutil.which(f"{name}.exe") or shutil.which(name)
        if found:
            return found
        raise ValueError(f"未找到软件「{name}」")
    if len(_RESOLVE_CACHE) < _CACHE_LIMIT:
        _RESOLVE_CACHE[key] = best
    return best


def _launch(target: str) -> None:
    """启动目标：快捷方式交给 Windows 解析，exe 用子进程拉起。"""
    if target.lower().endswith(".lnk"):
        os.startfile(target)  # noqa: S605 - 快捷方式由 Windows 解析
    else:
        subprocess.Popen([target], cwd=str(Path(target).parent))  # noqa: S603 - 已解析的本地软件路径


class LaunchAppTool(Tool):
    name = "launch_app"
    description = "启动/打开一个已安装的软件（按名称查找可执行文件或快捷方式）"
    risk = RiskLevel.SENSITIVE
    args_schema = {
        "type": "object",
        "properties": {
            "app": {"type": "string", "description": "要启动的软件名，如 Steam、微信、Google Chrome"},
        },
        "required": ["app"],
    }

    def plan(self, args: dict) -> ActionDetail:
        name = args.get("app", "").strip()
        target = resolve_app(name)
        return ActionDetail(
            summary=f"启动软件「{name}」",
            details=[f"将执行: {target}"],
            risk=self.risk,
        )

    def run(self, args: dict) -> ToolResult:
        name = args.get("app", "").strip()
        if not name:
            return ToolResult(ok=False, message="未指定要打开的软件名")
        try:
            target = resolve_app(name)
        except ValueError as e:
            return ToolResult(ok=False, message=str(e))
        try:
            _launch(target)
        except Exception as e:  # noqa: BLE001 - 覆盖 startfile/Popen 启动失败
            return ToolResult(ok=False, message=f"启动失败: {e}")
        return ToolResult(ok=True, message=f"已启动 {name}", data={"target": target})
