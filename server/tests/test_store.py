"""SQLite 存储层测试：任务/审计/信任/token 落盘与重开可读（模拟重启）。"""
from __future__ import annotations

from server.app.core.auth import Token
from server.app.core.jobs import Job
from server.app.core.store import Store


def _job() -> Job:
    return Job(
        id="j1",
        text="整理桌面",
        device_id="dev",
        status="done",
        tool_name="organize_desktop",
        args={"directory": "C:\\users\\me\\desktop"},
        result={"message": "ok", "count": 3},
    )


def test_job_roundtrip(tmp_path):
    store = Store(tmp_path / "t.db")
    store.save_job(_job())
    rows = store.load_all_jobs()
    assert len(rows) == 1
    assert rows[0]["id"] == "j1"
    assert rows[0]["status"] == "done"
    assert rows[0]["result"] == {"message": "ok", "count": 3}
    assert rows[0]["args"] == {"directory": "C:\\users\\me\\desktop"}
    assert rows[0]["device_id"] == "dev"


def test_job_reopen_persists(tmp_path):
    p = tmp_path / "t.db"
    Store(p).save_job(_job())
    # 模拟重启：新 Store 实例读同一文件
    rows = Store(p).load_all_jobs()
    assert rows[0]["id"] == "j1"


def test_audit_roundtrip(tmp_path):
    store = Store(tmp_path / "t.db")
    store.append_audit("批准 j1", 1000.0)
    store.append_audit("完成 j1", 1001.0)
    entries = store.load_audit()
    assert len(entries) == 2
    assert entries[0] == "完成 j1"  # 倒序
    assert "批准 j1" in entries


def test_trust_roundtrip_and_reopen(tmp_path):
    p = tmp_path / "t.db"
    Store(p).save_trust("dev", "organize_desktop", "C:\\desk", 2000.0)
    trusts = Store(p).load_trusts()
    assert ("dev", "organize_desktop", "C:\\desk", 2000.0) in trusts


def test_trust_delete(tmp_path):
    store = Store(tmp_path / "t.db")
    store.save_trust("dev", "t", "d", 2000.0)
    store.delete_trust("dev", "t", "d")
    assert store.load_trusts() == []
    store.save_trust("dev", "t", "d", 2000.0)
    store.save_trust("dev", "t", "d2", 2000.0)
    store.delete_trust_device("dev")
    assert store.load_trusts() == []


def test_token_roundtrip(tmp_path):
    p = tmp_path / "t.db"
    tok = Token(token="tok1", device_id="dev", created_at=100.0, expires_at=99999.0)
    Store(p).save_token(tok)
    rows = Store(p).load_tokens()
    assert ("tok1", "dev", 100.0, 99999.0) in rows
    Store(p).delete_token("tok1")
    assert Store(p).load_tokens() == []
