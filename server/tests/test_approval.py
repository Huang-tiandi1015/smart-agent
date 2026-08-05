"""审批记忆测试：remember/expire/revoke/restore。"""
from __future__ import annotations

import time

from server.app.core.approval import ApprovalCache
from server.app.core.store import Store


def test_remember_and_is_approved():
    cache = ApprovalCache()
    cache.remember("dev", "organize_desktop", "C:\\desk", 3600)
    assert cache.is_approved("dev", "organize_desktop", "C:\\desk")
    assert not cache.is_approved("dev", "organize_desktop", "C:\\other")
    assert not cache.is_approved("other", "organize_desktop", "C:\\desk")


def test_expire():
    cache = ApprovalCache()
    cache.remember("dev", "t", "d", 0.05)
    assert cache.is_approved("dev", "t", "d")
    time.sleep(0.08)
    assert not cache.is_approved("dev", "t", "d")


def test_ttl_zero_ignored():
    cache = ApprovalCache()
    cache.remember("dev", "t", "d", 0)
    assert not cache.is_approved("dev", "t", "d")


def test_revoke_device():
    cache = ApprovalCache()
    cache.remember("dev", "t", "d", 3600)
    cache.remember("dev", "t", "d2", 3600)
    cache.remember("other", "t", "d", 3600)
    cache.revoke_device("dev")
    assert not cache.is_approved("dev", "t", "d")
    assert not cache.is_approved("dev", "t", "d2")
    assert cache.is_approved("other", "t", "d")


def test_restore_from_store(tmp_path):
    store = Store(tmp_path / "t.db")
    cache1 = ApprovalCache(store=store)
    cache1.remember("dev", "t", "d", 3600)
    store.save_trust("expired", "t", "d", time.time() - 10)  # 已过期，恢复时剔除

    cache2 = ApprovalCache(store=store)
    cache2.restore()
    assert cache2.is_approved("dev", "t", "d")
    assert not cache2.is_approved("expired", "t", "d")
