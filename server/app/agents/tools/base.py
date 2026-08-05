"""Tool 抽象基类与危险级别。

新工具只需继承 Tool 并实现 plan/run，然后注册到 registry 即可，
规划器与审批机制自动生效，无需改动其他层。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    """危险级别：决定是否需经手机端审批。"""

    SAFE = "safe"           # 只读/无害，直接执行
    SENSITIVE = "sensitive"  # 修改用户数据，需审批
    DANGEROUS = "dangerous"  # 破坏性操作，严格审批 + 黑名单校验


@dataclass
class ActionDetail:
    """审批前展示给用户的动作明细（只描述，不改动）。"""

    summary: str
    details: list[str] = field(default_factory=list)
    risk: RiskLevel = RiskLevel.SAFE
    noop: bool = False  # True 表示无需实际操作，直接完成


@dataclass
class ToolResult:
    ok: bool
    message: str
    data: dict = field(default_factory=dict)


class Tool(ABC):
    name: str = ""
    description: str = ""
    risk: RiskLevel = RiskLevel.SAFE
    args_schema: dict = {}  # 简化 JSON Schema；里程碑 3 生成给大模型的 function definitions

    @abstractmethod
    def plan(self, args: dict) -> ActionDetail:
        """在审批前生成将执行的动作明细（禁止实际改动）。"""

    @abstractmethod
    def run(self, args: dict) -> ToolResult:
        """实际执行。"""
