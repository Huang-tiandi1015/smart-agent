"""pytest 公共夹具：强制 rules 规划器（不打真实 LLM）、FakeHub、任务管理器工厂。

里程碑 4：用 FakeHub 替代真实 WebSocket，测试状态机/审批/黑名单/持久化
时不依赖任何网络与外部设备。
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 必须在导入 server.app.config 之前设置，避免 .env 里的真实 key/模式覆盖测试配置
os.environ.setdefault("SMART_AGENT_PLANNER", "rules")
os.environ.setdefault("DEEPSEEK_API_KEY", "")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest  # noqa: E402

from server.app.core.jobs import TERMINAL, JobManager  # noqa: E402
from server.app.core.store import Store  # noqa: E402


class FakeHub:
    """记录所有推送消息，不连接真实 WebSocket。"""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def send_to_device(self, device_id: str, message: dict) -> bool:
        self.sent.append((device_id, message))
        return True


@pytest.fixture
def hub() -> FakeHub:
    return FakeHub()


@pytest.fixture
async def manager_factory(hub: FakeHub):
    """生成 JobManager 并追踪，teardown 时统一取消后台任务。"""
    managers: list[JobManager] = []

    def _make(store: Store | None = None, approval_ttl: float = 60.0) -> JobManager:
        m = JobManager(hub=hub, approval_ttl=approval_ttl, store=store)
        managers.append(m)
        return m

    yield _make
    for m in managers:
        await m.shutdown()


async def wait_status(manager: JobManager, job_id: str, statuses: set[str] = TERMINAL, timeout: float = 5.0):
    """轮询等待任务进入 statuses 中的任一状态；超时抛 AssertionError。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        job = manager.get(job_id)
        if job is not None and job.status in statuses:
            return job
        await asyncio.sleep(0.01)
    job = manager.get(job_id)
    raise AssertionError(
        f"job {job_id} 未进入 {statuses}，当前: {job.status if job else '不存在'}"
    )


def approval_requests(hub: FakeHub) -> list[dict]:
    """取出 hub 收到的所有审批请求消息。"""
    return [msg for _dev, msg in hub.sent if msg.get("type") == "approval_request"]
