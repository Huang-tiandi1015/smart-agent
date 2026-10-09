"""AuthManager 配对码逻辑单元测试（不依赖网络与外部设备）。"""
from __future__ import annotations

import time

from server.app.core.auth import AuthManager


def _make(**kw) -> AuthManager:
    return AuthManager(code_ttl=kw.get("code_ttl", 600), token_ttl=kw.get("token_ttl", 3600))


def test_current_pair_code_returns_existing():
    a = _make()
    issued = a.issue_pair_code()
    code, expires_at = a.current_pair_code()
    assert code == issued
    assert expires_at > time.time()


def test_current_pair_code_generates_when_all_expired():
    a = _make()
    issued = a.issue_pair_code()
    a._pair_codes[issued].expires_at = time.time() - 1
    code, expires_at = a.current_pair_code()
    assert code != issued
    assert expires_at > time.time()


def test_current_pair_code_generates_when_used_up():
    a = _make()
    issued = a.issue_pair_code()
    pc = a._pair_codes[issued]
    pc.used = pc.max_uses
    code, expires_at = a.current_pair_code()
    assert code != issued
    assert expires_at > time.time()


def test_current_pair_code_skips_used_up_but_keeps_valid():
    a = _make()
    first = a.issue_pair_code()
    second = a.issue_pair_code()
    a._pair_codes[first].used = a._pair_codes[first].max_uses  # 第一个用尽
    code, _ = a.current_pair_code()
    assert code == second  # 返回仍有效的新码


# ---------- 固定配对码 ----------

def _make_fixed(code="246813") -> AuthManager:
    return AuthManager(code_ttl=600, token_ttl=3600, fixed_code=code)


def test_fixed_code_issue_returns_same():
    a = _make_fixed()
    assert a.issue_pair_code() == "246813"
    assert a.issue_pair_code() == "246813"  # 重复调用仍返回同一个


def test_fixed_code_never_expires():
    a = _make_fixed()
    code, expires_at = a.current_pair_code()
    assert code == "246813"
    assert expires_at == 0  # 永不过期


def test_fixed_code_exchange_repeatedly():
    a = _make_fixed()
    a.issue_pair_code()
    # 远超默认 3 次上限仍可换取 token
    for _ in range(10):
        t = a.exchange("246813", f"dev-{_}")
        assert t is not None


def test_fixed_code_survives_cleanup():
    a = _make_fixed()
    a.issue_pair_code()
    a._cleanup()
    assert "246813" in a._pair_codes
    code, _ = a.current_pair_code()
    assert code == "246813"
