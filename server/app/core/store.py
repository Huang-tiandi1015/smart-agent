"""SQLite 持久化层：任务、审计、审批信任、token。

里程碑 4：MVP 阶段这些数据都在内存，重启即丢。本模块用 stdlib sqlite3
（零额外依赖）把四类数据落盘，每次操作独立开连接（WAL + busy_timeout），
无需常驻连接，单进程 MVP 足够。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with _connect(self.path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id          TEXT PRIMARY KEY,
                    text        TEXT NOT NULL,
                    device_id   TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    tool_name   TEXT,
                    args        TEXT,
                    result      TEXT,
                    error       TEXT,
                    created_at  REAL NOT NULL,
                    approved_at REAL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts    REAL NOT NULL,
                    entry TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approval_trust (
                    device_id  TEXT NOT NULL,
                    tool_name  TEXT NOT NULL,
                    directory  TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    PRIMARY KEY (device_id, tool_name, directory)
                );
                CREATE TABLE IF NOT EXISTS tokens (
                    token      TEXT PRIMARY KEY,
                    device_id  TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                """
            )

    # ---- jobs ----
    def save_job(self, job) -> None:
        """upsert 一个任务。job 需具备 id/text/device_id/status/tool_name/args/result/error/created_at/approved_at。"""
        with _connect(self.path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO jobs
                    (id, text, device_id, status, tool_name, args, result, error, created_at, approved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.text,
                    job.device_id,
                    job.status,
                    job.tool_name,
                    json.dumps(job.args, ensure_ascii=False) if job.args else None,
                    json.dumps(job.result, ensure_ascii=False) if job.result else None,
                    job.error,
                    job.created_at,
                    job.approved_at,
                ),
            )

    def load_all_jobs(self) -> list[dict]:
        with _connect(self.path) as conn:
            rows = conn.execute(
                "SELECT id, text, device_id, status, tool_name, args, result, error, created_at, approved_at FROM jobs"
            ).fetchall()
        return [
            {
                "id": r[0],
                "text": r[1],
                "device_id": r[2],
                "status": r[3],
                "tool_name": r[4],
                "args": json.loads(r[5]) if r[5] else {},
                "result": json.loads(r[6]) if r[6] else {},
                "error": r[7],
                "created_at": r[8],
                "approved_at": r[9],
            }
            for r in rows
        ]

    # ---- audit ----
    def append_audit(self, entry: str, ts: float) -> None:
        with _connect(self.path) as conn:
            conn.execute("INSERT INTO audit (ts, entry) VALUES (?, ?)", (ts, entry))

    def load_audit(self, limit: int = 100) -> list[str]:
        with _connect(self.path) as conn:
            rows = conn.execute(
                "SELECT entry FROM audit ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [r[0] for r in rows]

    # ---- approval trust ----
    def save_trust(self, device_id: str, tool_name: str, directory: str, expires_at: float) -> None:
        with _connect(self.path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO approval_trust (device_id, tool_name, directory, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (device_id, tool_name, directory, expires_at),
            )

    def load_trusts(self) -> list[tuple[str, str, str, float]]:
        with _connect(self.path) as conn:
            rows = conn.execute(
                "SELECT device_id, tool_name, directory, expires_at FROM approval_trust"
            ).fetchall()
        return rows

    def delete_trust(self, device_id: str, tool_name: str, directory: str) -> None:
        with _connect(self.path) as conn:
            conn.execute(
                "DELETE FROM approval_trust WHERE device_id=? AND tool_name=? AND directory=?",
                (device_id, tool_name, directory),
            )

    def delete_trust_device(self, device_id: str) -> None:
        with _connect(self.path) as conn:
            conn.execute("DELETE FROM approval_trust WHERE device_id=?", (device_id,))

    # ---- tokens ----
    def save_token(self, token) -> None:
        with _connect(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tokens (token, device_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token.token, token.device_id, token.created_at, token.expires_at),
            )

    def load_tokens(self) -> list[tuple[str, str, float, float]]:
        with _connect(self.path) as conn:
            rows = conn.execute("SELECT token, device_id, created_at, expires_at FROM tokens").fetchall()
        return rows

    def delete_token(self, token: str) -> None:
        with _connect(self.path) as conn:
            conn.execute("DELETE FROM tokens WHERE token=?", (token,))
