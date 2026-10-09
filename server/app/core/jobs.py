"""任务状态机与队列。

状态流转：
created -> parsing -> awaiting_approval -> approved/rejected -> executing -> done/failed/cancelled

里程碑 4：
- 任务/审计/审批信任落 SQLite（store 可选，为 None 时退化为纯内存）
- 重启恢复：非终态任务标记为「服务重启，任务中断」
- 取消：created/parsing/awaiting_approval 可取消
- 并发上限：工具执行用信号量限流
- DANGEROUS 工具必须审批，1h 信任不豁免
- 执行前黑名单硬拦截（safety/classifier）
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

from shared import protocol as p

from .. import config
from ..agents import planner
from ..agents.tools import registry
from ..agents.tools.base import ActionDetail, RiskLevel
from ..safety import classifier
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
STATUS_CANCELLED = "cancelled"

TERMINAL = {STATUS_DONE, STATUS_FAILED, STATUS_REJECTED, STATUS_CANCELLED}

# 可取消的状态
CANCELLABLE = {STATUS_CREATED, STATUS_PARSING, STATUS_AWAITING_APPROVAL}


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
    def __init__(self, hub: ConnectionHub, approval_ttl: float, store=None, max_concurrent: int | None = None) -> None:
        self._hub = hub
        self._approval_ttl = approval_ttl
        self._store = store
        self._exec_slots = asyncio.Semaphore(max_concurrent or config.MAX_CONCURRENT)
        self._jobs: dict[str, Job] = {}
        self._approval_cache = ApprovalCache(store=self._store)
        self._audit: list[str] = []
        self._tasks: set[asyncio.Task] = set()

    # ---- 对外接口 ----
    async def submit(self, device_id: str, text: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], text=text, device_id=device_id)
        self._jobs[job.id] = job
        await self._notify(job)
        self._spawn(self._process(job))
        return job

    async def handle_approval(self, device_id: str, job_id: str, decision: str, trust: str = "once") -> bool:
        """处理审批决定；仅任务发起设备可审批。"""
        job = self._jobs.get(job_id)
        if job is None or job.status != STATUS_AWAITING_APPROVAL or job.device_id != device_id:
            return False
        if decision == "approve":
            # 1h 信任仅对非 DANGEROUS 工具生效
            tool = registry.get_tool(job.tool_name or "") if job.tool_name else None
            if trust == "1h" and tool is not None and tool.risk != RiskLevel.DANGEROUS:
                self._approval_cache.remember(device_id, job.tool_name or "", job.args.get("directory", ""), 3600)
            job.approved_at = time.time()
            self._log_audit(f"批准 {job.id} {job.text}")
            await self._set_status(job, STATUS_APPROVED)
            self._spawn(self._execute(job))
        else:
            job.error = "用户拒绝执行"
            self._log_audit(f"拒绝 {job.id} {job.text}")
            await self._set_status(job, STATUS_REJECTED)
        return True

    async def cancel(self, device_id: str, job_id: str) -> bool:
        """取消等待审批/排队中的任务；仅任务发起设备可取消。"""
        job = self._jobs.get(job_id)
        if job is None or job.device_id != device_id or job.status not in CANCELLABLE:
            return False
        job.error = "用户取消"
        self._log_audit(f"取消 {job.id} {job.text}")
        await self._set_status(job, STATUS_CANCELLED)
        return True

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def recent(self, limit: int = 20) -> list[dict]:
        """最近任务摘要（供 get_recent 推送给手机端展示历史）。"""
        jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]
        return [
            {
                "job_id": j.id,
                "status": j.status,
                "text": j.text,
                "tool_name": j.tool_name,
                "error": j.error,
                "result": j.result if j.status in TERMINAL else {},
                "created_at": j.created_at,
            }
            for j in jobs
        ]

    def audit_log(self) -> list[str]:
        return list(self._audit)

    def restore(self) -> None:
        """从 store 恢复任务历史与审批信任；非终态任务标记为中断（启动时调用）。"""
        if not self._store:
            return
        for data in self._store.load_all_jobs():
            job = Job(
                id=data["id"], text=data["text"], device_id=data["device_id"], status=data["status"],
                tool_name=data["tool_name"], args=data["args"], result=data["result"],
                error=data["error"], created_at=data["created_at"], approved_at=data["approved_at"],
            )
            self._jobs[job.id] = job
            if job.status not in TERMINAL:
                job.status = STATUS_FAILED
                job.error = "服务重启，任务中断"
                self._log_audit(f"中断恢复 {job.id} {job.text}")
                self._store.save_job(job)
        self._approval_cache.restore()

    async def shutdown(self) -> None:
        """取消所有后台任务（服务关闭时调用，避免悬挂任务）。"""
        tasks = list(self._tasks)
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    # ---- 内部流程 ----
    async def _process(self, job: Job) -> None:
        await self._set_status(job, STATUS_PARSING)
        plan = await planner.plan_command(job.text)
        if plan.is_help or (plan.reply and plan.tool_name is None):
            job.result = {"reply": plan.reply}
            await self._set_status(job, STATUS_DONE)
            return
        tool = registry.get_tool(plan.tool_name) if plan.tool_name else None
        if tool is None:
            job.error = plan.reply or f"未找到工具: {plan.tool_name}"
            await self._set_status(job, STATUS_FAILED)
            return
        job.tool_name = tool.name
        job.args = plan.args
        try:
            # plan 可能做文件扫描等阻塞操作（如 launch_app 查找软件），移到线程避免卡事件循环
            job.action = await asyncio.to_thread(tool.plan, job.args)
        except Exception as e:  # noqa: BLE001
            job.error = f"规划失败: {e}"
            await self._set_status(job, STATUS_FAILED)
            return
        # 黑名单硬拦截：即使手机端批准，命中黑名单也直接拒绝
        decision = classifier.check_tool(tool, job.args)
        if not decision.allowed:
            job.error = f"安全拦截: {decision.reason}"
            self._log_audit(f"拦截 {job.id} {job.text}: {decision.reason}")
            await self._set_status(job, STATUS_FAILED)
            return
        if job.action.noop:  # 无实际动作，无需审批，直接完成
            job.result = {"reply": job.action.summary}
            await self._set_status(job, STATUS_DONE)
            return
        directory = job.args.get("directory", "")
        # DANGEROUS 工具必须审批，1h 信任不豁免
        needs_approval = tool.risk != RiskLevel.SAFE and (
            tool.risk == RiskLevel.DANGEROUS
            or not self._approval_cache.is_approved(job.device_id, tool.name, directory)
        )
        if not needs_approval:
            self._log_audit(f"免审批执行 {job.id} {job.text}")
            await self._execute(job)
            return
        await self._set_status(job, STATUS_AWAITING_APPROVAL)
        await self._push_approval_request(job)
        self._schedule_timeout(job)

    async def _execute(self, job: Job) -> None:
        tool = registry.get_tool(job.tool_name or "")
        if tool is None:
            job.error = f"未找到工具: {job.tool_name}"
            await self._set_status(job, STATUS_FAILED)
            return
        async with self._exec_slots:
            await self._set_status(job, STATUS_EXECUTING)
            try:
                result = await asyncio.to_thread(tool.run, job.args)
            except Exception as e:  # noqa: BLE001
                job.error = f"执行异常: {e}"
                self._log_audit(f"失败 {job.id} {e}")
                await self._set_status(job, STATUS_FAILED)
                return
            job.result = {"message": result.message, **result.data}
            if result.ok:
                self._log_audit(f"完成 {job.id} {job.text}: {result.message}")
                await self._set_status(job, STATUS_DONE)
            else:
                job.error = result.message
                await self._set_status(job, STATUS_FAILED)

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
                self._log_audit(f"超时拒绝 {job.id} {job.text}")
                await self._set_status(job, STATUS_REJECTED)

        self._spawn(_timeout())

    async def _set_status(self, job: Job, status: str) -> None:
        job.status = status
        if self._store:
            self._store.save_job(job)
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

    def _log_audit(self, entry: str) -> None:
        self._audit.append(f"{time.strftime('%F %T')} {entry}")
        if self._store:
            self._store.append_audit(entry, time.time())

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
