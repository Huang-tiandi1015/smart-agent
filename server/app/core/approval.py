"""审批记忆：用户选择「1 小时信任」后，同一设备对同一目录的同工具操作免审批。

里程碑 4：信任记录落 SQLite（重启不失效），`store` 为 None 时退化为纯内存。
"""
from __future__ import annotations

import time


class ApprovalCache:
    def __init__(self, store=None) -> None:
        self._store = store
        self._entries: dict[tuple[str, str, str], float] = {}  # (device, tool, directory) -> expires_at

    def remember(self, device_id: str, tool_name: str, directory: str, ttl: float) -> None:
        if ttl <= 0:
            return
        expires_at = time.time() + ttl
        self._entries[(device_id, tool_name, directory)] = expires_at
        if self._store:
            self._store.save_trust(device_id, tool_name, directory, expires_at)

    def is_approved(self, device_id: str, tool_name: str, directory: str) -> bool:
        key = (device_id, tool_name, directory)
        expires = self._entries.get(key)
        if expires is None:
            return False
        if time.time() > expires:
            del self._entries[key]
            if self._store:
                self._store.delete_trust(device_id, tool_name, directory)
            return False
        return True

    def revoke_device(self, device_id: str) -> None:
        for key in [k for k in self._entries if k[0] == device_id]:
            del self._entries[key]
        if self._store:
            self._store.delete_trust_device(device_id)

    def restore(self) -> None:
        """从 store 加载信任记录（启动时调用）。"""
        if not self._store:
            return
        now = time.time()
        for device_id, tool_name, directory, expires_at in self._store.load_trusts():
            if expires_at > now:
                self._entries[(device_id, tool_name, directory)] = expires_at
            else:
                self._store.delete_trust(device_id, tool_name, directory)
