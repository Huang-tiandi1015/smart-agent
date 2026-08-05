"""「整理桌面文件」工具：按类型把文件归档到子目录。

安全设计：
- 只移动文件，绝不删除/覆盖；
- 跳过目录、隐藏文件；
- 目标重名时自动加序号；
- 标记为 sensitive，执行前必须经手机端审批。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ... import config
from .base import ActionDetail, RiskLevel, Tool, ToolResult

CATEGORY_DIRS: dict[str, set[str]] = {
    "图片": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic", ".avif"},
    "文档": {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf", ".txt", ".md", ".csv", ".rtf"},
    "视频": {".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".webm", ".m4v"},
    "音频": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "压缩包": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "安装包": {".exe", ".msi", ".apk", ".dmg", ".pkg", ".deb"},
    "脚本": {".py", ".js", ".ts", ".sh", ".bat", ".cmd", ".ps1", ".html", ".css", ".json"},
}
OTHER_DIR = "其他"


def _categorize(path: Path) -> str:
    ext = path.suffix.lower()
    for cat, exts in CATEGORY_DIRS.items():
        if ext in exts:
            return cat
    return OTHER_DIR


class OrganizeDesktopTool(Tool):
    name = "organize_desktop"
    description = "按类型把目录下的文件归档到 图片/文档/视频… 子目录（仅移动，不删除）"
    risk = RiskLevel.SENSITIVE
    args_schema = {
        "type": "object",
        "properties": {
            "directory": {"type": "string", "description": "要整理的目录；省略时默认整理桌面目录"},
            "mode": {"type": "string", "enum": ["type"], "description": "归档方式，默认按类型"},
        },
        "required": [],
    }

    def plan(self, args: dict) -> ActionDetail:
        directory = Path(args.get("directory") or config.DESKTOP_DIR).expanduser()
        if not directory.is_dir():
            raise ValueError(f"目录不存在: {directory}")
        movable = self._collect(directory)
        if not movable:
            return ActionDetail(summary=f"「{directory}」下没有需要整理的文件", risk=self.risk, noop=True)
        by_cat: dict[str, list[Path]] = {}
        for f in movable:
            by_cat.setdefault(_categorize(f), []).append(f)
        lines = [f"将 {len(movable)} 个文件按类型归档到子目录（仅移动，不删除）："]
        for cat, files in sorted(by_cat.items()):
            samples = "、".join(f.name for f in files[:4])
            more = f" 等 {len(files)} 个" if len(files) > 4 else ""
            lines.append(f"  {cat} ← {samples}{more}")
        return ActionDetail(
            summary=f"把「{directory}」下 {len(movable)} 个文件按类型归类到子目录",
            details=lines,
            risk=self.risk,
        )

    def run(self, args: dict) -> ToolResult:
        directory = Path(args.get("directory") or config.DESKTOP_DIR).expanduser()
        if not directory.is_dir():
            return ToolResult(ok=False, message=f"目录不存在: {directory}")
        movable = self._collect(directory)
        if not movable:
            return ToolResult(ok=True, message="无需整理", data={"moved": [], "count": 0})
        moved: list[str] = []
        errors: list[str] = []
        for f in movable:
            dest_dir = directory / _categorize(f)
            dest_dir.mkdir(exist_ok=True)
            dest = dest_dir / f.name
            if dest.exists():  # 重名自动加序号
                stem, ext = f.stem, f.suffix
                i = 1
                while (dest_dir / f"{stem} ({i}){ext}").exists():
                    i += 1
                dest = dest_dir / f"{stem} ({i}){ext}"
            try:
                shutil.move(str(f), str(dest))
                moved.append(f"{f.name} -> {dest.parent.name}/")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{f.name}: {e}")
        data = {"moved": moved, "count": len(moved), "errors": errors, "directory": str(directory)}
        if errors:
            return ToolResult(ok=False, message=f"部分文件移动失败（{len(moved)} 成功 / {len(errors)} 失败）", data=data)
        return ToolResult(ok=True, message=f"已整理 {len(moved)} 个文件", data=data)

    def _collect(self, directory: Path) -> list[Path]:
        """收集需要移动的普通文件（跳过目录与隐藏文件）。"""
        return [child for child in directory.iterdir() if child.is_file() and not child.name.startswith(".")]
