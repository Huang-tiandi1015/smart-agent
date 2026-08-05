"""工具注册表：注册 -> 名称查找。

里程碑 3 将据此自动生成大模型的 function definitions，
新增工具只需在模块底部注册一行。
"""
from __future__ import annotations

from typing import Type

from .base import Tool
from .organize_desktop import OrganizeDesktopTool

_REGISTRY: dict[str, Type[Tool]] = {}


def register(tool_cls: Type[Tool]) -> None:
    _REGISTRY[tool_cls.name] = tool_cls


def get_tool(name: str) -> Tool | None:
    cls = _REGISTRY.get(name)
    return cls() if cls else None


def all_tools() -> list[Tool]:
    return [cls() for cls in _REGISTRY.values()]


def tool_names() -> list[str]:
    return list(_REGISTRY)


register(OrganizeDesktopTool)
