"""审批记忆：用户选择「1 小时信任」后，同一设备对同一目录的同工具操作免审批。

MVP 阶段存内存；里程碑 4 落库。
"""
from __future__ import annotations

import time


class ApprovalCache:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str, str], float] = {}  # (device, tool, directory) -> expires_at

    def remember(self, device_id: str, tool_name: str, directory: str, ttl: float) -> None:
        if ttl <= 0:
            return
        self._entries[(device_id, tool_name, directory)] = time.time() + ttl

    def is_approved(self, device_id: str, tool_name: str, directory: str) -> bool:
        key = (device_id, tool_name, directory)
        expires = self._entries.get(key)
        if expires is None:
            return False
        if time.time() > expires:
            del self._entries[key]
            return False
        return True

    def revoke_device(self, device_id: str) -> None:
        for key in [k for k in self._entries if k[0] == device_id]:
            del self._entries[key]
