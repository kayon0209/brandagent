from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent_api.domain.errors import ConflictError, ForbiddenError, NotFoundError
from agent_api.domain.models import AgentState, DecisionOutcome, ReviewSummary
from agent_api.repositories.leases import WorkflowLease, current_lease


class PostgresWorkflowRepository:
    def __init__(self, database_url: str, *, lease_seconds: float = 180) -> None:
        self._pool = AsyncConnectionPool(database_url, open=False, kwargs={"row_factory": dict_row})
        self._lease_seconds = lease_seconds

    def _lease(self, owner: str, version: int) -> WorkflowLease:
        return WorkflowLease(owner=owner, version=version, heartbeat_seconds=max(0.05, self._lease_seconds / 3))

    async def open(self) -> None:
        await self._pool.open()

    async def close(self) -> None:
        await self._pool.close()

    async def _scope(self, connection, workspace_id: str) -> None:
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))

    async def _assert_active_lease(self, connection) -> None:
        context = current_lease()
        if context is None:
            return
        cursor = await connection.execute(
            """SELECT 1 FROM idempotency_records
            WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s
              AND status='started' AND lease_owner=%s AND lease_version=%s
              AND lease_expires_at>NOW()""",
            (
                context.workspace_id,
                context.actor_id,
                context.action,
                context.idempotency_key,
                context.lease.owner,
                context.lease.version,
            ),
        )
        if await cursor.fetchone() is None:
            raise ConflictError("Workflow command lease is no longer active")

    async def assert_active_lease(self) -> None:
        async with self._pool.connection() as connection:
            context = current_lease()
            if context is not None:
                await self._scope(connection, context.workspace_id)
            await self._assert_active_lease(connection)

    @asynccontextmanager
    async def checkpoint_fence(self):
        context = current_lease()
        if context is None:
            yield
            return
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, context.workspace_id)
            cursor = await connection.execute(
                """SELECT 1 FROM idempotency_records
                WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s
                  AND status='started' AND lease_owner=%s AND lease_version=%s
                  AND lease_expires_at>NOW()
                FOR SHARE""",
                (
                    context.workspace_id,
                    context.actor_id,
                    context.action,
                    context.idempotency_key,
                    context.lease.owner,
                    context.lease.version,
                ),
            )
            if await cursor.fetchone() is None:
                raise ConflictError("Checkpoint lease is no longer active")
            yield

    async def is_cancelled(self, state: AgentState) -> bool:
        async with self._pool.connection() as connection:
            await self._scope(connection, state.workspace_id)
            cursor = await connection.execute(
                "SELECT cancellation_requested,status FROM content_tasks WHERE workspace_id=%s AND task_id=%s",
                (state.workspace_id, state.task_id),
            )
            row = await cursor.fetchone()
            return row is None or row["cancellation_requested"] or row["status"] == "cancelled"

    async def record(self, payload: dict[str, object]) -> None:
        async with self._pool.connection() as connection:
            await self._scope(connection, str(payload["workspace_id"]))
            await self._assert_active_lease(connection)
            await connection.execute(
                """INSERT INTO model_call_logs
                (model_call_id,workspace_id,task_id,provider,model,prompt_version,latency_ms,
                 input_tokens,output_tokens,usage_source,retry_count,status,error_code)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    str(uuid4()), payload["workspace_id"], payload["task_id"], payload["provider"],
                    payload["model"], payload["prompt_version"], payload["latency_ms"],
                    payload["input_tokens"], payload["output_tokens"], payload["usage_source"],
                    payload["retry_count"], payload["status"], payload["error_code"],
                ),
            )

    async def record_tool_call(self, payload: dict[str, object]) -> None:
        approval_requirement_id = None
        approval_requirement = None
        decision_id = payload.get("approval_decision_id")
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, str(payload["workspace_id"]))
            await self._assert_active_lease(connection)
            if decision_id:
                cursor = await connection.execute(
                    """SELECT d.approval_requirement_id,d.decision_type FROM human_decisions d
                    WHERE d.workspace_id=%s AND d.task_id=%s AND d.decision_id=%s""",
                    (payload["workspace_id"], payload["task_id"], decision_id),
                )
                decision = await cursor.fetchone()
                if decision:
                    approval_requirement_id = decision["approval_requirement_id"]
                    approval_requirement = decision["decision_type"]
            await connection.execute(
                """INSERT INTO tool_call_logs
                (tool_call_id,workspace_id,task_id,workflow_node,mcp_server,tool_name,capability,
                 sanitized_input,output_status,latency_ms,error_code,error_summary,approval_requirement,
                 approval_requirement_id,approval_decision_id,target_snapshot_hash,approval_result,
                 idempotency_key,request_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    str(uuid4()), payload["workspace_id"], payload["task_id"], payload["workflow_node"],
                    payload["mcp_server"], payload["tool_name"], payload["capability"],
                    json.dumps(payload["sanitized_input"]), payload["output_status"], payload["latency_ms"],
                    payload.get("error_code"), payload.get("error_summary"), approval_requirement,
                    approval_requirement_id, decision_id, payload.get("target_snapshot_hash"),
                    payload["approval_result"], payload.get("idempotency_key"), payload["request_id"],
                ),
            )

    async def persist_transition(self, state: AgentState, updates: dict[str, object], event_type: str) -> None:
        status = updates.get("status", state.status)
        status_value = status.value if hasattr(status, "value") else str(status)
        current_node = updates.get("current_node", state.current_node)
        error = updates.get("error", state.error)
        public_payload = {
            "status": status_value,
            "requires_human": bool(error and isinstance(error, dict) and error.get("requires_human")),
        }
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, state.workspace_id)
            await self._assert_active_lease(connection)
            updated = await connection.execute(
                """UPDATE content_tasks SET status=%s,current_node=%s,error=%s,updated_at=NOW()
                WHERE workspace_id=%s AND task_id=%s AND cancellation_requested=FALSE
                RETURNING task_id""",
                (status_value, current_node, json.dumps(error) if error else None, state.workspace_id, state.task_id),
            )
            if await updated.fetchone() is None:
                return
            await connection.execute(
                "INSERT INTO task_events(workspace_id,task_id,event_type,public_payload,workflow_node,request_id) VALUES(%s,%s,%s,%s,%s,%s)",
                (state.workspace_id, state.task_id, event_type, json.dumps(public_payload), current_node, f"workflow:{state.task_id}"),
            )

    async def retrieve(self, state: AgentState) -> dict[str, object]:
        if state.brief is None or state.brief.product_id is None or state.brief.brand_id is None:
            return {"verified_fact_ids": []}
        async with self._pool.connection() as connection:
            await self._scope(connection, state.workspace_id)
            facts_cursor = await connection.execute(
                """SELECT fact_id,source_document_id FROM verified_facts
                WHERE workspace_id=%s AND product_id=%s AND status='active'
                  AND public_usage_allowed=TRUE
                  AND (effective_at IS NULL OR effective_at<=NOW())
                  AND (expires_at IS NULL OR expires_at>NOW())
                ORDER BY CASE authority_level WHEN 'primary' THEN 1 WHEN 'approved' THEN 2 ELSE 3 END""",
                (state.workspace_id, state.brief.product_id),
            )
            facts = await facts_cursor.fetchall()
            guideline_cursor = await connection.execute(
                """SELECT version FROM brand_guideline_versions
                WHERE workspace_id=%s AND brand_id=%s AND active=TRUE
                  AND (effective_at IS NULL OR effective_at<=NOW())
                  AND (expires_at IS NULL OR expires_at>NOW())
                ORDER BY created_at DESC LIMIT 1""",
                (state.workspace_id, state.brief.brand_id),
            )
            guideline = await guideline_cursor.fetchone()
            specs: dict[str, str] = {}
            for channel in state.selected_channels:
                spec_cursor = await connection.execute(
                    "SELECT version FROM channel_spec_versions WHERE workspace_id=%s AND channel=%s AND active=TRUE ORDER BY created_at DESC LIMIT 1",
                    (state.workspace_id, channel.value),
                )
                spec = await spec_cursor.fetchone()
                if spec:
                    specs[channel.value] = spec["version"]
            return {
                "verified_fact_ids": [str(row["fact_id"]) for row in facts],
                "retrieved_source_ids": list({str(row["source_document_id"]) for row in facts}),
                "brand_guideline_version": guideline["version"] if guideline else None,
                "channel_spec_versions": specs,
            }

    async def get_content(self, *, state: AgentState, version_id: str) -> str:
        async with self._pool.connection() as connection:
            await self._scope(connection, state.workspace_id)
            cursor = await connection.execute(
                "SELECT content FROM content_versions WHERE workspace_id=%s AND task_id=%s AND content_version_id=%s",
                (state.workspace_id, state.task_id, version_id),
            )
            row = await cursor.fetchone()
            if row is None:
                raise NotFoundError("Content version not found")
            return row["content"]

    async def save(
        self,
        *,
        state: AgentState,
        content_type: str,
        content: str,
        parent_version_id: str | None = None,
    ) -> str:
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        version_id = str(uuid4())
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, state.workspace_id)
            await self._assert_active_lease(connection)
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"final-gate:{state.workspace_id}:{state.task_id}",),
            )
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"{state.workspace_id}:{state.task_id}:{content_type}:master",),
            )
            number_cursor = await connection.execute(
                "SELECT COALESCE(MAX(version_number),0)+1 AS next_number FROM content_versions WHERE workspace_id=%s AND task_id=%s AND content_type=%s AND channel IS NULL",
                (state.workspace_id, state.task_id, content_type),
            )
            next_number = (await number_cursor.fetchone())["next_number"]
            await connection.execute(
                """INSERT INTO content_versions
                (content_version_id,workspace_id,task_id,content_type,version_number,parent_version_id,
                 content,immutable_hash,created_by_type,created_by_id,prompt_version,change_summary)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'workflow','brandflow-agent-api','workflow-v1',%s)""",
                (
                    version_id,
                    state.workspace_id,
                    state.task_id,
                    content_type,
                    next_number,
                    parent_version_id,
                    content,
                    content_hash,
                    f"Created by {state.current_node or 'workflow'}",
                ),
            )
            if parent_version_id:
                await connection.execute(
                    """UPDATE approval_requirements
                    SET status='invalidated',invalidated_at=NOW(),invalidation_reason='Superseded by a revised version'
                    WHERE workspace_id=%s AND task_id=%s AND content_version_id=%s
                      AND status IN ('pending','satisfied')""",
                    (state.workspace_id, state.task_id, parent_version_id),
                )
            requirements = []
            if content_type == "master_outline":
                requirements = [("outline", "brand_reviewer")]
            elif content_type in {"master_draft", "master_revised"}:
                requirements = [("master_brand", "brand_reviewer"), ("master_final", "final_approver")]
            for decision_type, role in requirements:
                await connection.execute(
                    """INSERT INTO approval_requirements
                    (workspace_id,task_id,content_version_id,decision_type,required_role,target_snapshot_hash)
                    VALUES(%s,%s,%s,%s,%s,%s)""",
                    (state.workspace_id, state.task_id, version_id, decision_type, role, content_hash),
                )
        return version_id

    async def persist_reviews(self, state: AgentState, reviews: list[ReviewSummary]) -> None:
        if state.master_content_version_id is None:
            raise ValueError("Master content version is required")
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, state.workspace_id)
            await self._assert_active_lease(connection)
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"reviews:{state.workspace_id}:{state.master_content_version_id}",),
            )
            for review in reviews:
                existing_cursor = await connection.execute(
                    """SELECT review_id FROM review_results
                    WHERE workspace_id=%s AND task_id=%s AND content_version_id=%s
                      AND review_type=%s AND reviewer_type='deterministic' AND reviewer_version='master-review-v1'""",
                    (state.workspace_id, state.task_id, state.master_content_version_id, review.review_type),
                )
                if await existing_cursor.fetchone() is not None:
                    continue
                review_id = str(uuid4())
                await connection.execute(
                    """INSERT INTO review_results
                    (review_id,workspace_id,task_id,content_version_id,review_type,passed,max_severity,
                     revision_instructions,reviewer_type,reviewer_version)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'deterministic','master-review-v1')""",
                    (
                        review_id, state.workspace_id, state.task_id, state.master_content_version_id,
                        review.review_type, review.passed, None if review.passed else "critical",
                        json.dumps(review.revision_instructions),
                    ),
                )
                for issue in review.critical_issues:
                    await connection.execute(
                        """INSERT INTO review_issues
                        (workspace_id,task_id,review_id,issue_type,severity,reason,suggested_action)
                        VALUES(%s,%s,%s,%s,'critical',%s,%s)""",
                        (state.workspace_id, state.task_id, review_id, review.review_type, issue, f"Resolve {issue}"),
                    )

    async def record_decision(
        self,
        *,
        workspace_id: str,
        task_id: str,
        user_id: str,
        user_role: str,
        scope: str,
        content_version_id: str | None,
        target_snapshot_hash: str,
        decision: str,
        comment: str,
        idempotency_key: str,
        allow_new: bool = True,
    ) -> tuple[str, WorkflowLease | None]:
        decision_type = {
            "outline": "outline",
            "master_brand": "master_brand",
            "master_final": "master_final",
            "channel": "channel",
            "final_package": "final_package",
            "export": "export",
            "preview": "preview",
        }.get(scope)
        if decision_type is None:
            raise ValueError("Unsupported decision scope")
        action = f"decision:{decision_type}"
        request_payload = {
            "task_id": task_id,
            "content_version_id": content_version_id,
            "decision_type": decision_type,
            "decision": decision,
            "comment": comment,
            "user_id": user_id,
            "user_role": user_role,
            "target_snapshot_hash": target_snapshot_hash,
        }
        request_hash = hashlib.sha256(json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        lease_owner = str(uuid4())
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            member_cursor = await connection.execute(
                """SELECT 1 FROM workspace_members
                WHERE workspace_id=%s AND user_id=%s AND role=%s AND status='active'""",
                (workspace_id, user_id, user_role),
            )
            if await member_cursor.fetchone() is None:
                raise ForbiddenError("Active approval membership is required")
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"decision:{workspace_id}:{idempotency_key}",),
            )
            existing_cursor = await connection.execute(
                """SELECT decision_id,task_id,content_version_id,decision_type,decision,comment,
                          user_id,user_role,target_snapshot_hash
                FROM human_decisions WHERE workspace_id=%s AND idempotency_key=%s""",
                (workspace_id, idempotency_key),
            )
            existing = await existing_cursor.fetchone()
            if existing is not None:
                actual = {
                    key: str(existing[key]) if key in {"task_id", "content_version_id"} and existing[key] is not None else existing[key]
                    for key in request_payload
                }
                if actual != request_payload:
                    raise ConflictError("Idempotency key request mismatch")
                idempotency_cursor = await connection.execute(
                    """SELECT status,request_hash,
                              lease_owner,lease_version,lease_expires_at<=NOW() AS lease_expired
                    FROM idempotency_records WHERE workspace_id=%s AND actor_id=%s
                      AND action=%s AND idempotency_key=%s FOR UPDATE""",
                    (workspace_id, user_id, action, idempotency_key),
                )
                idempotency = await idempotency_cursor.fetchone()
                if idempotency is None:
                    await connection.execute(
                        """INSERT INTO idempotency_records
                        (workspace_id,actor_id,action,immutable_target,idempotency_key,request_hash,status,
                         response_status,response_body,lease_owner,lease_version,lease_expires_at,expires_at)
                        VALUES(%s,%s,%s,%s,%s,%s,'started',200,%s,%s,1,
                               NOW()+(%s * INTERVAL '1 second'),NOW()+INTERVAL '24 hours')""",
                        (workspace_id, user_id, action, content_version_id or target_snapshot_hash, idempotency_key, request_hash, json.dumps({"decision_id": str(existing["decision_id"])}), lease_owner, self._lease_seconds),
                    )
                    return str(existing["decision_id"]), self._lease(lease_owner, 1)
                if idempotency["request_hash"] != request_hash:
                    raise ConflictError("Idempotency key request hash mismatch")
                if idempotency["status"] == "succeeded":
                    return str(existing["decision_id"]), None
                if not idempotency["lease_expired"]:
                    raise ConflictError("Idempotent request is already in progress")
                task_cursor = await connection.execute(
                    "SELECT status FROM content_tasks WHERE workspace_id=%s AND task_id=%s FOR UPDATE",
                    (workspace_id, task_id),
                )
                task = await task_cursor.fetchone()
                expected_status = {
                    "outline": "waiting_for_outline_approval",
                    "master_brand": "waiting_for_master_approval",
                    "master_final": "waiting_for_master_approval",
                    "channel": "reviewing_channels",
                    "final_package": "waiting_for_final_approval",
                    "export": "completed",
                    "preview": "completed",
                }[decision_type]
                if task and task["status"] != expected_status:
                    await connection.execute(
                        """UPDATE idempotency_records SET status='succeeded',updated_at=NOW()
                        WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s""",
                        (workspace_id, user_id, action, idempotency_key),
                    )
                    return str(existing["decision_id"]), None
                await connection.execute(
                    """UPDATE idempotency_records SET lease_owner=%s,lease_version=lease_version+1,
                        lease_expires_at=NOW()+(%s * INTERVAL '1 second'),updated_at=NOW()
                    WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s""",
                    (lease_owner, self._lease_seconds, workspace_id, user_id, action, idempotency_key),
                )
                version_cursor = await connection.execute(
                    "SELECT lease_version FROM idempotency_records WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s",
                    (workspace_id, user_id, action, idempotency_key),
                )
                return str(existing["decision_id"]), self._lease(lease_owner, (await version_cursor.fetchone())["lease_version"])
            if not allow_new:
                raise ConflictError("Task is not waiting for this approval")
            requirement_cursor = await connection.execute(
                """SELECT approval_requirement_id,target_snapshot_hash FROM approval_requirements
                WHERE workspace_id=%s AND task_id=%s AND content_version_id IS NOT DISTINCT FROM %s
                  AND decision_type=%s AND required_role=%s AND status='pending' FOR UPDATE""",
                (workspace_id, task_id, content_version_id, decision_type, user_role),
            )
            requirement = await requirement_cursor.fetchone()
            if requirement is None:
                raise ForbiddenError("Pending approval requirement not found")
            if requirement["target_snapshot_hash"] != target_snapshot_hash:
                raise ForbiddenError("Approval snapshot does not match the pending requirement")
            decision_id = str(uuid4())
            await connection.execute(
                """INSERT INTO idempotency_records
                (workspace_id,actor_id,action,immutable_target,idempotency_key,request_hash,status,
                 response_status,response_body,lease_owner,lease_version,lease_expires_at,expires_at)
                VALUES(%s,%s,%s,%s,%s,%s,'started',200,%s,%s,1,
                       NOW()+(%s * INTERVAL '1 second'),NOW()+INTERVAL '24 hours')""",
                (workspace_id, user_id, action, content_version_id or target_snapshot_hash, idempotency_key, request_hash, json.dumps({"decision_id": decision_id}), lease_owner, self._lease_seconds),
            )
            await connection.execute(
                """INSERT INTO human_decisions
                (decision_id,workspace_id,task_id,content_version_id,approval_requirement_id,
                 decision_type,decision,comment,user_id,user_role,target_snapshot_hash,idempotency_key,request_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    decision_id, workspace_id, task_id, content_version_id,
                    requirement["approval_requirement_id"], decision_type, decision, comment,
                    user_id, user_role, target_snapshot_hash, idempotency_key, f"approval:{decision_id}",
                ),
            )
            return decision_id, self._lease(lease_owner, 1)

    async def complete_decision_idempotency(
        self,
        *,
        workspace_id: str,
        user_id: str,
        decision_type: str,
        idempotency_key: str,
        task: dict[str, object],
        lease: WorkflowLease,
    ) -> None:
        action = f"decision:{decision_type}"
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            updated = await connection.execute(
                """UPDATE idempotency_records SET status='succeeded',response_body=%s,updated_at=NOW()
                WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s
                  AND status='started' AND lease_owner=%s AND lease_version=%s
                RETURNING idempotency_record_id""",
                (json.dumps(task, default=str), workspace_id, user_id, action, idempotency_key, lease.owner, lease.version),
            )
            if await updated.fetchone() is None:
                existing = await connection.execute(
                    """SELECT status FROM idempotency_records
                    WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s""",
                    (workspace_id, user_id, action, idempotency_key),
                )
                row = await existing.fetchone()
                raise ConflictError("Decision command lease was lost")

    async def renew_decision_lease(
        self,
        *,
        workspace_id: str,
        user_id: str,
        decision_type: str,
        idempotency_key: str,
        lease: WorkflowLease,
    ) -> bool:
        action = f"decision:{decision_type}"
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            renewed = await connection.execute(
                """UPDATE idempotency_records
                SET lease_expires_at=NOW()+(%s * INTERVAL '1 second'),updated_at=NOW()
                WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s
                  AND status='started' AND lease_owner=%s AND lease_version=%s
                RETURNING idempotency_record_id""",
                (self._lease_seconds, workspace_id, user_id, action, idempotency_key, lease.owner, lease.version),
            )
            return await renewed.fetchone() is not None

    async def resolve(
        self,
        *,
        decision_id: str,
        state: AgentState,
        scope: str,
        version_id: str | None,
    ) -> DecisionOutcome:
        if version_id is None:
            return DecisionOutcome(valid=False, decision="invalid")
        allowed_types = {"outline": {"outline"}, "master": {"master_brand", "master_final"}}.get(scope)
        if not allowed_types:
            return DecisionOutcome(valid=False, decision="invalid")
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, state.workspace_id)
            decision_cursor = await connection.execute(
                """SELECT d.decision_type,d.decision,d.comment,d.target_snapshot_hash,
                          v.immutable_hash,r.status AS requirement_status
                FROM human_decisions d
                JOIN approval_requirements r ON r.workspace_id=d.workspace_id AND r.approval_requirement_id=d.approval_requirement_id
                JOIN content_versions v ON v.workspace_id=d.workspace_id AND v.content_version_id=d.content_version_id
                WHERE d.workspace_id=%s AND d.task_id=%s AND d.decision_id=%s
                  AND d.content_version_id=%s
                FOR SHARE OF r,v""",
                (state.workspace_id, state.task_id, decision_id, version_id),
            )
            decision = await decision_cursor.fetchone()
            if not decision or decision["decision_type"] not in allowed_types:
                return DecisionOutcome(valid=False, decision="invalid")
            if decision["target_snapshot_hash"] != decision["immutable_hash"]:
                return DecisionOutcome(valid=False, decision="invalid")
            if decision["decision"] == "reject" and decision["requirement_status"] == "rejected":
                return DecisionOutcome(valid=True, decision="reject", comment=decision["comment"])
            if decision["decision"] != "approve" or decision["requirement_status"] != "satisfied":
                return DecisionOutcome(valid=False, decision="invalid")
            if scope == "master":
                aggregate_cursor = await connection.execute(
                    """SELECT decision_type,status,target_snapshot_hash FROM approval_requirements
                    WHERE workspace_id=%s AND task_id=%s AND content_version_id=%s
                      AND decision_type IN ('master_brand','master_final')""",
                    (state.workspace_id, state.task_id, version_id),
                )
                requirements = await aggregate_cursor.fetchall()
                complete = {row["decision_type"] for row in requirements if row["status"] == "satisfied" and row["target_snapshot_hash"] == decision["immutable_hash"]} == {"master_brand", "master_final"}
                return DecisionOutcome(valid=True, decision="approve" if complete else "pending", comment=decision["comment"])
            return DecisionOutcome(valid=True, decision="approve", comment=decision["comment"])
