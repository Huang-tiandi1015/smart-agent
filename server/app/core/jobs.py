"""任务状态机与队列。

状态流转：
created -> parsing -> awaiting_approval -> approved/rejected -> executing -> done/failed
MVP 阶段任务存内存（重启丢失）；里程碑 4 迁移 SQLite 支持恢复。
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

from shared import protocol as p

from ..agents import planner
from ..agents.tools import registry
from ..agents.tools.base import ActionDetail, RiskLevel
from ..core.approval import ApprovalCache
from ..core.hub import ConnectionHub

logger = logging.getLogger("smart-agent.jobs")

STATUS_CREATED = "created"
STATUS_PARSING = "parsing"
STATUS_AWAITING_APPROVAL = "awaiting_approval"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_EXECUTING = "executing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

TERMINAL = {STATUS_DONE, STATUS_FAILED, STATUS_REJECTED}


@dataclass
class Job:
    id: str
    text: str
    device_id: str
    status: str = STATUS_CREATED
    tool_name: str | None = None
    args: dict = field(default_factory=dict)
    action: ActionDetail | None = None
    result: dict = field(default_factory=dict)
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    approved_at: float | None = None


class JobManager:
    def __init__(self, hub: ConnectionHub, approval_ttl: float) -> None:
        self._hub = hub
        self._approval_ttl = approval_ttl
        self._jobs: dict[str, Job] = {}
        self._approval_cache = ApprovalCache()
        self._audit: list[str] = []

    # ---- 对外接口 ----
    async def submit(self, device_id: str, text: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], text=text, device_id=device_id)
        self._jobs[job.id] = job
        await self._notify(job)
        asyncio.create_task(self._process(job))
        return job

    async def handle_approval(self, device_id: str, job_id: str, decision: str, trust: str = "once") -> bool:
        """处理审批决定；仅任务发起设备可审批。"""
        job = self._jobs.get(job_id)
        if job is None or job.status != STATUS_AWAITING_APPROVAL or job.device_id != device_id:
            return False
        if decision == "approve":
            if trust == "1h":
                self._approval_cache.remember(device_id, job.tool_name or "", job.args.get("directory", ""), 3600)
            job.approved_at = time.time()
            self._audit.append(f"{time.strftime('%F %T')} 批准 {job.id} {job.text}")
            await self._set_status(job,STATUS_APPROVED)
            asyncio.create_task(self._execute(job))
        else:
            job.error = "用户拒绝执行"
            self._audit.append(f"{time.strftime('%F %T')} 拒绝 {job.id} {job.text}")
            await self._set_status(job,STATUS_REJECTED)
        return True

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def recent(self, limit: int = 20) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]

    def audit_log(self) -> list[str]:
        return list(self._audit)

    # ---- 内部流程 ----
    async def _process(self, job: Job) -> None:
        await self._set_status(job,STATUS_PARSING)
        plan = await planner.plan_command(job.text)
        if plan.is_help or (plan.reply and plan.tool_name is None):
            job.result = {"reply": plan.reply}
            await self._set_status(job,STATUS_DONE)
            return
        tool = registry.get_tool(plan.tool_name) if plan.tool_name else None
        if tool is None:
            job.error = plan.reply or f"未找到工具: {plan.tool_name}"
            await self._set_status(job,STATUS_FAILED)
            return
        job.tool_name = tool.name
        job.args = plan.args
        try:
            job.action = tool.plan(job.args)
        except Exception as e:  # noqa: BLE001
            job.error = f"规划失败: {e}"
            await self._set_status(job,STATUS_FAILED)
            return
        if job.action.noop:  # 无实际动作，无需审批，直接完成
            job.result = {"reply": job.action.summary}
            await self._set_status(job,STATUS_DONE)
            return
        directory = job.args.get("directory", "")
        if tool.risk == RiskLevel.SAFE or self._approval_cache.is_approved(job.device_id, tool.name, directory):
            self._audit.append(f"{time.strftime('%F %T')} 免审批执行 {job.id} {job.text}")
            await self._execute(job)
            return
        await self._set_status(job,STATUS_AWAITING_APPROVAL)
        await self._push_approval_request(job)
        self._schedule_timeout(job)

    async def _execute(self, job: Job) -> None:
        tool = registry.get_tool(job.tool_name or "")
        if tool is None:
            job.error = f"未找到工具: {job.tool_name}"
            await self._set_status(job,STATUS_FAILED)
            return
        await self._set_status(job,STATUS_EXECUTING)
        try:
            result = await asyncio.to_thread(tool.run, job.args)
        except Exception as e:  # noqa: BLE001
            job.error = f"执行异常: {e}"
            self._audit.append(f"{time.strftime('%F %T')} 失败 {job.id} {e}")
            await self._set_status(job,STATUS_FAILED)
            return
        job.result = {"message": result.message, **result.data}
        if result.ok:
            self._audit.append(f"{time.strftime('%F %T')} 完成 {job.id} {job.text}: {result.message}")
            await self._set_status(job,STATUS_DONE)
        else:
            job.error = result.message
            await self._set_status(job,STATUS_FAILED)

    # ---- 推送与审计 ----
    async def _push_approval_request(self, job: Job) -> None:
        action = job.action
        msg = p.make_message(
            p.MSG_APPROVAL_REQUEST,
            job_id=job.id,
            text=job.text,
            risk=action.risk.value if action else "unknown",
            summary=action.summary if action else "",
            details=action.details if action else [],
            ttl=self._approval_ttl,
        )
        await self._hub.send_to_device(job.device_id, msg)

    def _schedule_timeout(self, job: Job) -> None:
        async def _timeout() -> None:
            await asyncio.sleep(self._approval_ttl)
            if job.status == STATUS_AWAITING_APPROVAL:
                job.error = "审批超时，已自动拒绝"
                self._audit.append(f"{time.strftime('%F %T')} 超时拒绝 {job.id} {job.text}")
                await self._set_status(job,STATUS_REJECTED)

        asyncio.create_task(_timeout())

    async def _set_status(self, job: Job, status: str) -> None:
        job.status = status
        await self._notify(job)

    async def _notify(self, job: Job) -> None:
        msg = p.make_message(
            p.MSG_JOB_STATUS,
            job_id=job.id,
            status=job.status,
            text=job.text,
            tool_name=job.tool_name,
            error=job.error,
            result=job.result if job.status in TERMINAL else {},
        )
        await self._hub.send_to_device(job.device_id, msg)
        logger.info("job %s -> %s (%s)", job.id, job.status, job.text)
