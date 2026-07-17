from __future__ import annotations

import asyncio
from contextlib import suppress
from collections.abc import Awaitable, Callable

from langgraph.types import Command

from agent_api.api.models import CreateTaskRequest, DecisionRequest
from agent_api.api.security import Principal
from agent_api.domain.errors import ConflictError, ForbiddenError
from agent_api.domain.models import AgentState, Channel, ContentBrief
from agent_api.providers.base import LLMProvider, ProviderExecutionError
from agent_api.providers.logged import LoggedLLMProvider
from agent_api.repositories.postgres_tasks import PostgresTaskRepository
from agent_api.repositories.postgres_workflow import PostgresWorkflowRepository
from agent_api.repositories.leases import LeaseContext, WorkflowLease, bind_lease, reset_lease
from agent_api.workflow.checkpoint import FencedCheckpointer, checkpoint_config
from agent_api.workflow.graph import build_master_content_graph
from agent_api.workflow.services import WorkflowDependencies
from agent_api.application.channels import ChannelWorkflowService
from agent_api.repositories.postgres_channels import PostgresChannelStore
from agent_api.mcp.client import RealMCPClient
from agent_api.evaluation.metrics import EvaluationService
from agent_api.evaluation.diffing import version_diff
from agent_api.repositories.postgres_evaluation import PostgresEvaluationStore


class TaskWorkflowService:
    def __init__(
        self,
        *,
        tasks: PostgresTaskRepository,
        workflow: PostgresWorkflowRepository,
        provider: LLMProvider,
        checkpointer,
        context=None,
        channel_store: PostgresChannelStore | None = None,
        channels: ChannelWorkflowService | None = None,
        tools: RealMCPClient | None = None,
        evaluation_store: PostgresEvaluationStore | None = None,
        evaluation: EvaluationService | None = None,
    ) -> None:
        self._tasks = tasks
        self._workflow = workflow
        self._provider = provider
        self._checkpointer = checkpointer
        self._context = context
        self._channel_store = channel_store
        self._channels = channels
        self._tools = tools
        self._evaluation_store = evaluation_store
        self._evaluation = evaluation

    async def _run_leased(
        self,
        operation: Awaitable,
        lease: WorkflowLease,
        renew: Callable[[], Awaitable[bool]],
        context: LeaseContext,
    ):
        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(lease.heartbeat_seconds)
                if not await renew():
                    raise ConflictError("Workflow command lease was lost")

        context_token = bind_lease(context)
        try:
            operation_task = asyncio.create_task(operation)
        finally:
            reset_lease(context_token)
        heartbeat_task = asyncio.create_task(heartbeat())
        done, _pending = await asyncio.wait(
            {operation_task, heartbeat_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if operation_task in done:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            return await operation_task
        operation_task.cancel()
        with suppress(asyncio.CancelledError):
            await operation_task
        await heartbeat_task

    def _graph(self, *, workspace_id: str, task_id: str):
        provider = LoggedLLMProvider(
            self._provider,
            self._workflow,
            workspace_id=workspace_id,
            task_id=task_id,
        )

        dependencies = WorkflowDependencies(
            provider=provider,
            context=self._context or self._workflow,
            versions=self._workflow,
            decisions=self._workflow,
            runtime=self._workflow,
        )
        checkpointer = FencedCheckpointer(self._checkpointer, self._workflow) if self._checkpointer else None
        return build_master_content_graph(dependencies, checkpointer=checkpointer)

    async def bootstrap_workspace(self, principal: Principal) -> dict:
        return await self._tasks.bootstrap_workspace(principal)

    async def _invoke(self, *, principal: Principal, task_id: str, value):
        graph = self._graph(workspace_id=principal.workspace_id, task_id=task_id)
        try:
            return await graph.ainvoke(value, checkpoint_config(workspace_id=principal.workspace_id, task_id=task_id))
        except ProviderExecutionError as error:
            state = AgentState(task_id=task_id, workspace_id=principal.workspace_id, user_id=principal.user_id)
            await self._workflow.persist_transition(
                state,
                {
                    "status": "failed",
                    "current_node": "handle_model_failure",
                    "error": {
                        "code": error.code,
                        "message": str(error),
                        "recoverable": error.retryable,
                        "saved_work_safe": True,
                        "requires_human": not error.retryable,
                    },
                },
                "error",
            )
            return None

    async def create_task(self, principal: Principal, request: CreateTaskRequest, idempotency_key: str) -> dict:
        task = await self._tasks.create_task(principal, request, idempotency_key)
        lease = task.pop("_dispatch_lease", None)
        if lease:
            state = AgentState(
                task_id=task["task_id"],
                workspace_id=principal.workspace_id,
                user_id=principal.user_id,
                brief=ContentBrief(
                    task_id=task["task_id"],
                    workspace_id=principal.workspace_id,
                    **request.brief.model_dump(),
                ),
                selected_channels=request.selected_channels,
            )
            await self._run_leased(
                self._invoke(principal=principal, task_id=task["task_id"], value=state),
                lease,
                lambda: self._tasks.renew_idempotency_lease(principal, "create_task", idempotency_key, lease),
                LeaseContext(principal.workspace_id, principal.user_id, "create_task", idempotency_key, lease),
            )
        result = await self._tasks.get_task(principal, task["task_id"])
        if lease:
            await self._tasks.complete_idempotency(principal, "create_task", idempotency_key, result, lease)
        return result

    async def get_task(self, principal: Principal, task_id: str) -> dict:
        return await self._tasks.get_task(principal, task_id)

    async def list_tasks(self, principal: Principal) -> list[dict]:
        return await self._tasks.list_tasks(principal)

    async def cancel_task(self, principal: Principal, task_id: str, idempotency_key: str) -> dict:
        return await self._tasks.cancel_task(principal, task_id, idempotency_key)

    async def retry_task(self, principal: Principal, task_id: str, idempotency_key: str) -> dict:
        lease = await self._tasks.claim_retry(principal, task_id, idempotency_key)
        if lease:
            await self._run_leased(
                self._invoke(principal=principal, task_id=task_id, value=None),
                lease,
                lambda: self._tasks.renew_idempotency_lease(principal, "retry_task", idempotency_key, lease),
                LeaseContext(principal.workspace_id, principal.user_id, "retry_task", idempotency_key, lease),
            )
        result = await self._tasks.get_task(principal, task_id)
        if lease:
            await self._tasks.complete_idempotency(principal, "retry_task", idempotency_key, result, lease)
        return result

    async def get_events(self, principal: Principal, task_id: str, after_event_id: int) -> list[dict]:
        return await self._tasks.get_events(principal, task_id, after_event_id)

    async def generate_channels(self, principal: Principal, task_id: str, idempotency_key: str) -> dict:
        if self._channels is None or self._channel_store is None:
            raise RuntimeError("Channel workflow is unavailable")
        await self._tasks.require_operator(principal)
        await self._tasks.get_task(principal, task_id)
        context = await self._channel_store.task_context(principal.workspace_id, task_id)
        if not context or not context.get("product_id"):
            raise ForbiddenError("A verified product is required for channel generation")
        selected = [Channel(channel) for channel in context["selected_channels"]]
        action = "generate_channels"
        request = {"task_id": task_id, "product_id": context["product_id"], "channels": [channel.value for channel in selected]}
        lease, replay = await self._channel_store.claim_operation(principal.workspace_id, principal.user_id, action, idempotency_key, task_id, request)
        if replay is not None:
            return replay

        async def execute() -> dict:
            await self._channel_store.set_task_stage(principal.workspace_id, task_id, "generating_channels", "generate_channel_variants", "channel_generation_started", {"channels": [channel.value for channel in selected]})
            result = await self._channels.generate(
                workspace_id=principal.workspace_id, task_id=task_id, actor_id=principal.user_id,
                product_id=context["product_id"], channels=selected,
            )
            await self._channel_store.set_task_stage(principal.workspace_id, task_id, "reviewing_channels", "review_channel_variants", "channel_review_completed", {"channels": result})
            return {"task_id": task_id, "channels": result, "status": "reviewing_channels"}

        assert lease is not None
        response = await self._run_leased(
            execute(), lease,
            lambda: self._channel_store.renew_operation(principal.workspace_id, principal.user_id, action, idempotency_key, lease),
            LeaseContext(principal.workspace_id, principal.user_id, action, idempotency_key, lease),
        )
        await self._channel_store.complete_operation(principal.workspace_id, principal.user_id, action, idempotency_key, response, lease)
        return response

    async def prepare_final_approval(self, principal: Principal, task_id: str) -> dict:
        if self._channels is None or self._channel_store is None:
            raise RuntimeError("Channel workflow is unavailable")
        task = await self._tasks.get_task(principal, task_id)
        required = [Channel(channel) for channel in task["selected_channels"]]
        requirement = await self._channels.final_gate(
            workspace_id=principal.workspace_id,
            task_id=task_id,
            required_channels=required,
        )
        await self._channel_store.set_task_stage(principal.workspace_id, task_id, "waiting_for_final_approval", "request_final_approval", "human_approval_required", {"scope": "final_package", "requirement": requirement})
        return {"task_id": task_id, "status": "waiting_for_final_approval", "approval_requirement": requirement}

    async def revise_channel(self, principal: Principal, task_id: str, channel: Channel, instructions: list[str], idempotency_key: str) -> dict:
        if self._channels is None or self._channel_store is None:
            raise RuntimeError("Channel workflow is unavailable")
        await self._tasks.require_operator(principal)
        context = await self._channel_store.task_context(principal.workspace_id, task_id)
        if not context or not context.get("product_id") or channel.value not in context["selected_channels"]:
            raise ForbiddenError("The selected channel or verified product is unavailable")
        action = f"revise_channel:{channel.value}"
        request = {"task_id": task_id, "channel": channel.value, "instructions": instructions}
        lease, replay = await self._channel_store.claim_operation(principal.workspace_id, principal.user_id, action, idempotency_key, task_id, request)
        if replay is not None:
            return replay

        async def execute() -> dict:
            result = await self._channels.revise(
                workspace_id=principal.workspace_id, task_id=task_id, actor_id=principal.user_id,
                product_id=context["product_id"], channel=channel, instructions=instructions,
            )
            await self._channel_store.set_task_stage(principal.workspace_id, task_id, "reviewing_channels", f"revise_channel:{channel.value}", "channel_revision_completed", result)
            return result

        assert lease is not None
        response = await self._run_leased(
            execute(), lease,
            lambda: self._channel_store.renew_operation(principal.workspace_id, principal.user_id, action, idempotency_key, lease),
            LeaseContext(principal.workspace_id, principal.user_id, action, idempotency_key, lease),
        )
        await self._channel_store.complete_operation(principal.workspace_id, principal.user_id, action, idempotency_key, response, lease)
        return response

    async def export_package(self, principal: Principal, task_id: str, *, decision_id: str, target_snapshot_hash: str, formats: list[str], idempotency_key: str) -> dict:
        if self._tools is None or self._channel_store is None:
            raise RuntimeError("Export tools are unavailable")
        await self._tasks.get_task(principal, task_id)
        await self._channel_store.set_task_stage(principal.workspace_id, task_id, "exporting", "export_content_package", "export_started", {"formats": formats})
        client = self._tools.for_actor(workspace_id=principal.workspace_id, task_id=task_id, workflow_node="export_content_package", actor_id=principal.user_id)
        try:
            result = await client.call("export_content_package", {
                "workspace_id": principal.workspace_id, "task_id": task_id, "actor_id": principal.user_id,
                "decision_id": decision_id, "target_snapshot_hash": target_snapshot_hash,
                "idempotency_key": idempotency_key, "formats": formats,
            })
        except Exception as error:
            await self._channel_store.set_task_stage(
                principal.workspace_id, task_id, "completed", "export_content_package", "export_failed",
                {"saved_work_safe": True, "recoverable": True, "error_code": getattr(error, "code", "EXPORT_FAILED")},
            )
            raise
        await self._channel_store.set_task_stage(principal.workspace_id, task_id, "completed", "export_content_package", "export_completed", {"formats": formats, "package_hash": target_snapshot_hash})
        return result["data"]

    async def create_preview(self, principal: Principal, task_id: str, *, decision_id: str, target_snapshot_hash: str, idempotency_key: str) -> dict:
        if self._tools is None:
            raise RuntimeError("Preview tools are unavailable")
        await self._tasks.get_task(principal, task_id)
        client = self._tools.for_actor(workspace_id=principal.workspace_id, task_id=task_id, workflow_node="create_publish_preview", actor_id=principal.user_id)
        result = await client.call("create_publish_preview", {
            "workspace_id": principal.workspace_id, "task_id": task_id, "actor_id": principal.user_id,
            "decision_id": decision_id, "target_snapshot_hash": target_snapshot_hash,
            "idempotency_key": idempotency_key,
        })
        return result["data"]

    async def run_evaluation(self, principal: Principal) -> dict:
        if self._evaluation is None:
            raise RuntimeError("Evaluation service is unavailable")
        await self._tasks.require_active_member(principal)
        return await self._evaluation.run(principal.workspace_id)

    async def evaluation_report(self, principal: Principal, run_id: str, format: str) -> tuple[str, str]:
        if self._evaluation is None:
            raise RuntimeError("Evaluation service is unavailable")
        await self._tasks.require_active_member(principal)
        return await self._evaluation.report(principal.workspace_id, run_id, format)

    async def compare_versions(self, principal: Principal, task_id: str, parent_id: str, current_id: str) -> dict:
        if self._evaluation_store is None:
            raise RuntimeError("Version comparison is unavailable")
        await self._tasks.get_task(principal, task_id)
        parent, current = await self._evaluation_store.versions(principal.workspace_id, task_id, parent_id, current_id)
        return version_diff(parent, current)

    async def list_bad_cases(self, principal: Principal) -> list[dict]:
        if self._evaluation_store is None:
            raise RuntimeError("Bad-case service is unavailable")
        await self._tasks.require_active_member(principal)
        return await self._evaluation_store.bad_cases(principal.workspace_id)

    async def get_workspace(self, principal: Principal, task_id: str) -> dict:
        if self._channel_store is None:
            raise RuntimeError("Task workspace is unavailable")
        task = await self._tasks.get_task(principal, task_id)
        snapshot = await self._channel_store.workspace_snapshot(principal.workspace_id, task_id)
        return {"task": task, **snapshot}

    async def answer_clarification(self, principal: Principal, task_id: str, answers: dict[str, object], idempotency_key: str) -> dict:
        lease = await self._tasks.persist_clarification(principal, task_id, answers, idempotency_key)
        if lease:
            await self._run_leased(
                self._invoke(principal=principal, task_id=task_id, value=Command(resume=answers)),
                lease,
                lambda: self._tasks.renew_idempotency_lease(principal, "answer_clarification", idempotency_key, lease),
                LeaseContext(principal.workspace_id, principal.user_id, "answer_clarification", idempotency_key, lease),
            )
        result = await self._tasks.get_task(principal, task_id)
        if lease:
            await self._tasks.complete_idempotency(principal, "answer_clarification", idempotency_key, result, lease)
        return result

    async def decide(self, principal: Principal, task_id: str, scope: str, request: DecisionRequest, idempotency_key: str) -> dict:
        task = await self._tasks.get_task(principal, task_id)
        if task["status"] == "cancelled":
            raise ForbiddenError("Cancelled tasks cannot be resumed")
        expected_status = {
            "outline": "waiting_for_outline_approval",
            "master": "waiting_for_master_approval",
            "channel": "reviewing_channels",
            "final_package": "waiting_for_final_approval",
        }.get(scope)
        if expected_status is None:
            raise ForbiddenError("Unsupported approval scope")
        effective_scope = scope
        if scope == "master":
            effective_scope = "master_brand" if principal.role == "brand_reviewer" else "master_final"
        decision_id, lease = await self._workflow.record_decision(
            workspace_id=principal.workspace_id,
            task_id=task_id,
            user_id=principal.user_id,
            user_role=principal.role,
            scope=effective_scope,
            content_version_id=request.content_version_id,
            target_snapshot_hash=request.target_snapshot_hash,
            decision=request.decision,
            comment=request.comment,
            idempotency_key=idempotency_key,
            allow_new=task["status"] == expected_status,
        )
        if lease and scope in {"outline", "master"}:
            await self._run_leased(
                self._invoke(principal=principal, task_id=task_id, value=Command(resume={"decision_id": decision_id})),
                lease,
                lambda: self._workflow.renew_decision_lease(
                    workspace_id=principal.workspace_id,
                    user_id=principal.user_id,
                    decision_type=effective_scope,
                    idempotency_key=idempotency_key,
                    lease=lease,
                ),
                LeaseContext(principal.workspace_id, principal.user_id, f"decision:{effective_scope}", idempotency_key, lease),
            )
        result = await self._tasks.get_task(principal, task_id)
        if lease and scope in {"channel", "final_package"} and self._channel_store is not None:
            if scope == "final_package":
                await self._channel_store.set_task_stage(
                    principal.workspace_id, task_id,
                    "completed" if request.decision == "approve" else "reviewing_channels",
                    "wait_for_final_approval",
                    "final_approved" if request.decision == "approve" else "revision_requested",
                    {"decision": request.decision},
                )
                result = await self._tasks.get_task(principal, task_id)
        if lease:
            await self._workflow.complete_decision_idempotency(
                workspace_id=principal.workspace_id,
                user_id=principal.user_id,
                decision_type=effective_scope,
                idempotency_key=idempotency_key,
                task=result,
                lease=lease,
            )
        return result

    async def decide_channel(self, principal: Principal, task_id: str, channel: Channel, request: DecisionRequest, idempotency_key: str) -> dict:
        if self._channel_store is None or request.content_version_id is None:
            raise ForbiddenError("A channel content version is required")
        current = await self._channel_store.current_variant(principal.workspace_id, task_id, channel.value)
        if not current or current["content_version_id"] != request.content_version_id:
            raise ForbiddenError("Approval target does not match the channel in the request path")
        return await self.decide(principal, task_id, "channel", request, idempotency_key)
