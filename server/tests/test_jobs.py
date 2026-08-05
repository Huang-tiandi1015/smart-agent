"""任务状态机测试：批准/拒绝/帮助/空目录/1h 信任/危险工具不豁免/取消/黑名单/重启恢复。"""
from __future__ import annotations

import pytest

from server.app.agents import planner as planner_mod
from server.app.agents.planner import PlanResult
from server.app.agents.tools import registry
from server.app.agents.tools.base import ActionDetail, RiskLevel, Tool, ToolResult
from server.app.core.jobs import (
    STATUS_AWAITING_APPROVAL,
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_REJECTED,
)
from server.app.core.store import Store

from conftest import approval_requests, wait_status


class DummyDangerTool(Tool):
    """测试专用危险工具：真实产品工具集中不存在。"""

    name = "_dummy_danger"
    description = "测试用危险工具"
    risk = RiskLevel.DANGEROUS
    args_schema = {
        "type": "object",
        "properties": {"directory": {"type": "string"}},
        "required": [],
    }

    def plan(self, args: dict) -> ActionDetail:
        return ActionDetail(summary="模拟危险操作", risk=self.risk)

    def run(self, args: dict) -> ToolResult:
        return ToolResult(ok=True, message="危险操作已执行")


@pytest.fixture
def danger_tool():
    registry.register(DummyDangerTool)
    yield DummyDangerTool
    registry._REGISTRY.pop(DummyDangerTool.name, None)


def _desk(tmp_path, *names: str):
    """建一个含指定文件的临时目录，返回目录路径字符串。"""
    d = tmp_path / "desk"
    d.mkdir()
    for name in names:
        (d / name).write_bytes(b"\x89PNG\r\n")
    return str(d)


async def _plan_danger(text: str) -> PlanResult:
    return PlanResult(tool_name=DummyDangerTool.name, args={})


# ---- 基础状态流 ----

async def test_approve_runs_tool(manager_factory, tmp_path):
    manager = manager_factory()
    d = _desk(tmp_path, "a.txt", "b.png")
    job = await manager.submit("dev", f"整理 {d}")
    await wait_status(manager, job.id, {STATUS_AWAITING_APPROVAL})
    assert await manager.handle_approval("dev", job.id, "approve")
    job = await wait_status(manager, job.id)
    assert job.status == STATUS_DONE
    assert job.result.get("count") == 2
    assert (tmp_path / "desk" / "文档" / "a.txt").exists()
    assert (tmp_path / "desk" / "图片" / "b.png").exists()


async def test_reject(manager_factory, tmp_path):
    manager = manager_factory()
    d = _desk(tmp_path, "a.txt")
    job = await manager.submit("dev", f"整理 {d}")
    await wait_status(manager, job.id, {STATUS_AWAITING_APPROVAL})
    assert await manager.handle_approval("dev", job.id, "deny")
    job = await wait_status(manager, job.id, {STATUS_REJECTED})
    assert job.error == "用户拒绝执行"


async def test_approval_wrong_device_rejected(manager_factory, tmp_path):
    manager = manager_factory()
    d = _desk(tmp_path, "a.txt")
    job = await manager.submit("dev", f"整理 {d}")
    await wait_status(manager, job.id, {STATUS_AWAITING_APPROVAL})
    assert not await manager.handle_approval("other", job.id, "approve")
    assert manager.get(job.id).status == STATUS_AWAITING_APPROVAL


async def test_help_reply(manager_factory):
    manager = manager_factory()
    job = await manager.submit("dev", "帮助")
    job = await wait_status(manager, job.id)
    assert job.status == STATUS_DONE
    assert "支持的指令" in job.result.get("reply", "")


async def test_unknown_command_reply(manager_factory):
    manager = manager_factory()
    job = await manager.submit("dev", "随便说点什么")
    job = await wait_status(manager, job.id)
    assert job.status == STATUS_DONE
    assert "未识别" in job.result.get("reply", "")


async def test_empty_dir_noop_skips_approval(manager_factory, hub, tmp_path):
    manager = manager_factory()
    d = tmp_path / "empty"
    d.mkdir()
    job = await manager.submit("dev", f"整理 {d}")
    job = await wait_status(manager, job.id)
    assert job.status == STATUS_DONE
    assert approval_requests(hub) == []


# ---- 1 小时信任 ----

async def test_trust_1h_waives_sensitive(manager_factory, hub, tmp_path):
    manager = manager_factory()
    d = _desk(tmp_path, "a.txt")
    job1 = await manager.submit("dev", f"整理 {d}")
    await wait_status(manager, job1.id, {STATUS_AWAITING_APPROVAL})
    assert await manager.handle_approval("dev", job1.id, "approve", trust="1h")
    await wait_status(manager, job1.id)

    job2 = await manager.submit("dev", f"整理 {d}")
    job2 = await wait_status(manager, job2.id)
    assert job2.status == STATUS_DONE

    reqs = approval_requests(hub)
    assert len(reqs) == 1  # 只有第一次弹过审批
    assert reqs[0]["job_id"] == job1.id


async def test_dangerous_trust_1h_not_waived(manager_factory, hub, danger_tool, monkeypatch):
    manager = manager_factory()
    monkeypatch.setattr(planner_mod, "plan_command", _plan_danger)

    job1 = await manager.submit("dev", "测试危险")
    await wait_status(manager, job1.id, {STATUS_AWAITING_APPROVAL})
    assert await manager.handle_approval("dev", job1.id, "approve", trust="1h")
    await wait_status(manager, job1.id)

    # DANGEROUS 工具 1h 信任不豁免 → 第二次仍需审批
    job2 = await manager.submit("dev", "测试危险")
    job2 = await wait_status(manager, job2.id, {STATUS_AWAITING_APPROVAL})
    assert job2.status == STATUS_AWAITING_APPROVAL
    assert len(approval_requests(hub)) == 2


# ---- 取消 ----

async def test_cancel_awaiting(manager_factory, tmp_path):
    manager = manager_factory()
    d = _desk(tmp_path, "a.txt")
    job = await manager.submit("dev", f"整理 {d}")
    await wait_status(manager, job.id, {STATUS_AWAITING_APPROVAL})
    assert await manager.cancel("dev", job.id)
    job = await wait_status(manager, job.id, {STATUS_CANCELLED})
    assert job.error == "用户取消"


async def test_cancel_wrong_device(manager_factory, tmp_path):
    manager = manager_factory()
    d = _desk(tmp_path, "a.txt")
    job = await manager.submit("dev", f"整理 {d}")
    await wait_status(manager, job.id, {STATUS_AWAITING_APPROVAL})
    assert not await manager.cancel("other", job.id)
    assert manager.get(job.id).status == STATUS_AWAITING_APPROVAL


async def test_cancel_done_fails(manager_factory, tmp_path):
    manager = manager_factory()
    d = _desk(tmp_path, "a.txt")
    job = await manager.submit("dev", f"整理 {d}")
    await wait_status(manager, job.id, {STATUS_AWAITING_APPROVAL})
    await manager.handle_approval("dev", job.id, "approve")
    await wait_status(manager, job.id)
    assert not await manager.cancel("dev", job.id)


# ---- 安全：黑名单硬拦截 ----

async def test_blacklist_hard_block(manager_factory, tmp_path):
    manager = manager_factory()
    job = await manager.submit("dev", "整理 C:\\Windows")
    job = await wait_status(manager, job.id)
    assert job.status == STATUS_FAILED
    assert "安全拦截" in (job.error or "")
    assert "c:\\windows" in (job.error or "")


# ---- 持久化：重启恢复 ----

async def test_restore_marks_interrupted(manager_factory, tmp_path):
    store = Store(tmp_path / "data.db")
    manager1 = manager_factory(store=store)
    d = _desk(tmp_path, "a.txt")
    job = await manager1.submit("dev", f"整理 {d}")
    await wait_status(manager1, job.id, {STATUS_AWAITING_APPROVAL})

    manager2 = manager_factory(store=store)
    manager2.restore()
    restored = manager2.get(job.id)
    assert restored is not None
    assert restored.status == STATUS_FAILED
    assert "服务重启，任务中断" in (restored.error or "")
    assert restored.text == f"整理 {d}"


async def test_restore_keeps_terminal_done(manager_factory, tmp_path):
    store = Store(tmp_path / "data.db")
    manager1 = manager_factory(store=store)
    d = _desk(tmp_path, "a.txt")
    job = await manager1.submit("dev", f"整理 {d}")
    await wait_status(manager1, job.id, {STATUS_AWAITING_APPROVAL})
    await manager1.handle_approval("dev", job.id, "approve")
    await wait_status(manager1, job.id)

    manager2 = manager_factory(store=store)
    manager2.restore()
    restored = manager2.get(job.id)
    assert restored.status == STATUS_DONE
