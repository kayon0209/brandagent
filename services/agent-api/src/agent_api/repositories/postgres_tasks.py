from __future__ import annotations

import hashlib
import json
from uuid import uuid4
from datetime import UTC, datetime

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent_api.api.models import CreateTaskRequest
from agent_api.api.security import Principal
from agent_api.domain.errors import ConflictError, ForbiddenError, NotFoundError
from agent_api.repositories.leases import WorkflowLease


RepositoryConflict = ConflictError
RepositoryNotFound = NotFoundError


class PostgresTaskRepository:
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

    async def _require_active_member(self, connection, principal: Principal) -> str:
        member = await connection.execute(
            "SELECT role, status FROM workspace_members WHERE workspace_id=%s AND user_id=%s",
            (principal.workspace_id, principal.user_id),
        )
        row = await member.fetchone()
        if not row or row["status"] != "active" or row["role"] != principal.role:
            raise RepositoryNotFound("Resource not found")
        return row["role"]

    async def _require_operator(self, connection, principal: Principal) -> None:
        role = await self._require_active_member(connection, principal)
        if role not in {"content_operator", "admin"}:
            raise ForbiddenError("Active content operator membership is required")

    async def require_operator(self, principal: Principal) -> None:
        async with self._pool.connection() as connection:
            await self._scope(connection, principal.workspace_id)
            await self._require_operator(connection, principal)

    async def require_active_member(self, principal: Principal) -> None:
        async with self._pool.connection() as connection:
            await self._scope(connection, principal.workspace_id)
            await self._require_active_member(connection, principal)

    async def bootstrap_workspace(self, principal: Principal) -> dict:
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, principal.workspace_id)
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"workspace-bootstrap:{principal.workspace_id}",),
            )
            workspace_cursor = await connection.execute(
                "SELECT workspace_id FROM workspaces WHERE workspace_id=%s FOR UPDATE",
                (principal.workspace_id,),
            )
            workspace = await workspace_cursor.fetchone()
            created = workspace is None
            if created:
                if principal.role != "admin":
                    raise ForbiddenError("A workspace administrator must initialize this organization")
                await connection.execute(
                    """INSERT INTO workspaces(workspace_id,name,slug,created_by)
                    VALUES(%s,'BrandFlow workspace',%s,%s)""",
                    (principal.workspace_id, f"workspace-{principal.workspace_id}", principal.user_id),
                )
            member_cursor = await connection.execute(
                "SELECT role,status FROM workspace_members WHERE workspace_id=%s AND user_id=%s FOR UPDATE",
                (principal.workspace_id, principal.user_id),
            )
            member = await member_cursor.fetchone()
            if member and member["status"] != "active":
                raise ForbiddenError("Workspace membership is not active")
            if member:
                if member["role"] != principal.role:
                    await connection.execute(
                        "UPDATE workspace_members SET role=%s WHERE workspace_id=%s AND user_id=%s",
                        (principal.role, principal.workspace_id, principal.user_id),
                    )
            else:
                await connection.execute(
                    """INSERT INTO workspace_members(workspace_id,user_id,role,status)
                    VALUES(%s,%s,%s,'active')""",
                    (principal.workspace_id, principal.user_id, principal.role),
                )
            return {"workspace_id": principal.workspace_id, "role": principal.role, "created": created}

    async def create_task(self, principal: Principal, request: CreateTaskRequest, idempotency_key: str) -> dict:
        payload = request.model_dump(mode="json")
        request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        lease_owner = str(uuid4())
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, principal.workspace_id)
            await self._require_operator(connection, principal)
            inserted = await connection.execute(
                """INSERT INTO idempotency_records
                (workspace_id,actor_id,action,immutable_target,idempotency_key,request_hash,status,
                 lease_owner,lease_version,lease_expires_at,expires_at)
                VALUES (%s,%s,'create_task','new-task',%s,%s,'started',%s,1,
                        NOW()+(%s * INTERVAL '1 second'),NOW()+INTERVAL '24 hours')
                ON CONFLICT (workspace_id,actor_id,action,idempotency_key) DO NOTHING
                RETURNING idempotency_record_id""",
                (principal.workspace_id, principal.user_id, idempotency_key, request_hash, lease_owner, self._lease_seconds),
            )
            if await inserted.fetchone() is None:
                existing_cursor = await connection.execute(
                    """SELECT request_hash,status,response_body,
                              lease_owner,lease_version,lease_expires_at<=NOW() AS lease_expired
                    FROM idempotency_records WHERE workspace_id=%s AND actor_id=%s
                      AND action='create_task' AND idempotency_key=%s FOR UPDATE""",
                    (principal.workspace_id, principal.user_id, idempotency_key),
                )
                existing = await existing_cursor.fetchone()
                if existing["request_hash"] != request_hash:
                    raise RepositoryConflict("Idempotency key request hash mismatch")
                if existing["status"] == "succeeded" and existing["response_body"]:
                    return {**existing["response_body"], "_dispatch_lease": None}
                if not existing["lease_expired"]:
                    raise RepositoryConflict("Idempotent request is already in progress")
                task_cursor = await connection.execute(
                    "SELECT status,current_node FROM content_tasks WHERE workspace_id=%s AND task_id=%s FOR UPDATE",
                    (principal.workspace_id, existing["response_body"]["task_id"]),
                )
                task = await task_cursor.fetchone()
                if task and (task["status"] != "draft" or task["current_node"] is not None):
                    await connection.execute(
                        """UPDATE idempotency_records SET status='succeeded',updated_at=NOW()
                        WHERE workspace_id=%s AND actor_id=%s AND action='create_task' AND idempotency_key=%s""",
                        (principal.workspace_id, principal.user_id, idempotency_key),
                    )
                    return {**existing["response_body"], "_dispatch_lease": None}
                reclaimed = await connection.execute(
                    """UPDATE idempotency_records SET lease_owner=%s,lease_version=lease_version+1,
                        lease_expires_at=NOW()+(%s * INTERVAL '1 second'),updated_at=NOW()
                    WHERE workspace_id=%s AND actor_id=%s AND action='create_task' AND idempotency_key=%s""",
                    (lease_owner, self._lease_seconds, principal.workspace_id, principal.user_id, idempotency_key),
                )
                version_cursor = await connection.execute(
                    "SELECT lease_version FROM idempotency_records WHERE workspace_id=%s AND actor_id=%s AND action='create_task' AND idempotency_key=%s",
                    (principal.workspace_id, principal.user_id, idempotency_key),
                )
                version = (await version_cursor.fetchone())["lease_version"]
                return {**existing["response_body"], "_dispatch_lease": self._lease(lease_owner, version)}

            task_id = str(uuid4())
            await connection.execute(
                "INSERT INTO content_tasks(task_id,workspace_id,user_id,title,status,selected_channels) VALUES(%s,%s,%s,%s,'draft',%s)",
                (task_id, principal.workspace_id, principal.user_id, request.title, [channel.value for channel in request.selected_channels]),
            )
            await connection.execute(
                "INSERT INTO task_events(workspace_id,task_id,event_type,public_payload,workflow_node,request_id) VALUES(%s,%s,'task_started',%s,'create_task',%s)",
                (principal.workspace_id, task_id, json.dumps({"status": "draft"}), f"create:{idempotency_key}"),
            )
            brief = request.brief
            await connection.execute(
                """INSERT INTO content_briefs
                (workspace_id,task_id,topic,brand_id,product_id,target_audience,publishing_objective,primary_channel,desired_audience_action)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (principal.workspace_id, task_id, brief.topic, brief.brand_id, brief.product_id, brief.target_audience, brief.publishing_objective, brief.primary_channel.value if brief.primary_channel else None, brief.desired_audience_action),
            )
            result = {"task_id": task_id, "workspace_id": principal.workspace_id, "user_id": principal.user_id, "title": request.title, "status": "draft", "selected_channels": [channel.value for channel in request.selected_channels], "current_node": None}
            await connection.execute(
                "UPDATE idempotency_records SET response_status=201,response_body=%s,updated_at=NOW() WHERE workspace_id=%s AND actor_id=%s AND action='create_task' AND idempotency_key=%s",
                (json.dumps(result), principal.workspace_id, principal.user_id, idempotency_key),
            )
            return {**result, "_dispatch_lease": self._lease(lease_owner, 1)}

    async def complete_idempotency(
        self,
        principal: Principal,
        action: str,
        idempotency_key: str,
        response_body: dict[str, object],
        lease: WorkflowLease,
    ) -> None:
        if action not in {"create_task", "answer_clarification", "retry_task"}:
            raise ValueError("Unsupported idempotent action")
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, principal.workspace_id)
            updated = await connection.execute(
                """UPDATE idempotency_records SET status='succeeded',response_body=%s,updated_at=NOW()
                WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s
                  AND status='started' AND lease_owner=%s AND lease_version=%s
                RETURNING idempotency_record_id""",
                (json.dumps(response_body, default=str), principal.workspace_id, principal.user_id, action, idempotency_key, lease.owner, lease.version),
            )
            if await updated.fetchone() is None:
                existing = await connection.execute(
                    """SELECT status FROM idempotency_records
                    WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s""",
                    (principal.workspace_id, principal.user_id, action, idempotency_key),
                )
                row = await existing.fetchone()
                raise RepositoryConflict("Idempotent command lease was lost")

    async def renew_idempotency_lease(
        self,
        principal: Principal,
        action: str,
        idempotency_key: str,
        lease: WorkflowLease,
    ) -> bool:
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, principal.workspace_id)
            renewed = await connection.execute(
                """UPDATE idempotency_records
                SET lease_expires_at=NOW()+(%s * INTERVAL '1 second'),updated_at=NOW()
                WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s
                  AND status='started' AND lease_owner=%s AND lease_version=%s
                RETURNING idempotency_record_id""",
                (self._lease_seconds, principal.workspace_id, principal.user_id, action, idempotency_key, lease.owner, lease.version),
            )
            return await renewed.fetchone() is not None

    async def get_task(self, principal: Principal, task_id: str) -> dict:
        async with self._pool.connection() as connection:
            await self._scope(connection, principal.workspace_id)
            await self._require_active_member(connection, principal)
            cursor = await connection.execute(
                "SELECT task_id,workspace_id,user_id,title,status,selected_channels,current_node,error,cancellation_requested FROM content_tasks WHERE workspace_id=%s AND task_id=%s",
                (principal.workspace_id, task_id),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RepositoryNotFound("Task not found")
            return {key: str(value) if key in {"task_id", "workspace_id"} else value for key, value in row.items()}

    async def persist_clarification(
        self,
        principal: Principal,
        task_id: str,
        answers: dict[str, object],
        idempotency_key: str,
    ) -> WorkflowLease | None:
        allowed_fields = {
            "topic", "brand_id", "product_id", "target_audience",
            "publishing_objective", "primary_channel", "desired_audience_action",
        }
        updates = {key: value for key, value in answers.items() if key in allowed_fields}
        if not updates:
            raise RepositoryConflict("No supported clarification answers were provided")
        request_hash = hashlib.sha256(json.dumps(updates, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        lease_owner = str(uuid4())
        answered_at = datetime.now(UTC).isoformat()
        history = [{"question": key, "answer": str(value), "answered_at": answered_at} for key, value in updates.items()]
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, principal.workspace_id)
            await self._require_operator(connection, principal)
            inserted = await connection.execute(
                """INSERT INTO idempotency_records
                (workspace_id,actor_id,action,immutable_target,idempotency_key,request_hash,status,
                 lease_owner,lease_version,lease_expires_at,expires_at)
                VALUES(%s,%s,'answer_clarification',%s,%s,%s,'started',%s,1,
                       NOW()+(%s * INTERVAL '1 second'),NOW()+INTERVAL '24 hours')
                ON CONFLICT (workspace_id,actor_id,action,idempotency_key) DO NOTHING
                RETURNING idempotency_record_id""",
                (principal.workspace_id, principal.user_id, task_id, idempotency_key, request_hash, lease_owner, self._lease_seconds),
            )
            if await inserted.fetchone() is None:
                existing_cursor = await connection.execute(
                    """SELECT request_hash,status,
                              lease_owner,lease_version,lease_expires_at<=NOW() AS lease_expired
                    FROM idempotency_records
                    WHERE workspace_id=%s AND actor_id=%s AND action='answer_clarification' AND idempotency_key=%s
                    FOR UPDATE""",
                    (principal.workspace_id, principal.user_id, idempotency_key),
                )
                existing = await existing_cursor.fetchone()
                if existing["request_hash"] != request_hash:
                    raise RepositoryConflict("Idempotency key request hash mismatch")
                if existing["status"] == "succeeded":
                    return None
                if not existing["lease_expired"]:
                    raise RepositoryConflict("Idempotent request is already in progress")
                task_cursor = await connection.execute(
                    "SELECT status FROM content_tasks WHERE workspace_id=%s AND task_id=%s FOR UPDATE",
                    (principal.workspace_id, task_id),
                )
                task = await task_cursor.fetchone()
                if task is None:
                    raise RepositoryNotFound("Task not found")
                if task["status"] != "waiting_for_clarification":
                    await connection.execute(
                        """UPDATE idempotency_records SET status='succeeded',updated_at=NOW()
                        WHERE workspace_id=%s AND actor_id=%s AND action='answer_clarification' AND idempotency_key=%s""",
                        (principal.workspace_id, principal.user_id, idempotency_key),
                    )
                    return None
                await connection.execute(
                    """UPDATE idempotency_records SET lease_owner=%s,lease_version=lease_version+1,
                        lease_expires_at=NOW()+(%s * INTERVAL '1 second'),updated_at=NOW()
                    WHERE workspace_id=%s AND actor_id=%s AND action='answer_clarification' AND idempotency_key=%s""",
                    (lease_owner, self._lease_seconds, principal.workspace_id, principal.user_id, idempotency_key),
                )
                version_cursor = await connection.execute(
                    "SELECT lease_version FROM idempotency_records WHERE workspace_id=%s AND actor_id=%s AND action='answer_clarification' AND idempotency_key=%s",
                    (principal.workspace_id, principal.user_id, idempotency_key),
                )
                return self._lease(lease_owner, (await version_cursor.fetchone())["lease_version"])
            task_cursor = await connection.execute(
                "SELECT status FROM content_tasks WHERE workspace_id=%s AND task_id=%s FOR UPDATE",
                (principal.workspace_id, task_id),
            )
            task = await task_cursor.fetchone()
            if task is None:
                raise RepositoryNotFound("Task not found")
            if task["status"] != "waiting_for_clarification":
                raise RepositoryConflict("Task is not waiting for clarification")
            await connection.execute(
                """UPDATE content_briefs SET
                topic=COALESCE(%s,topic),brand_id=COALESCE(%s::uuid,brand_id),
                product_id=COALESCE(%s::uuid,product_id),target_audience=COALESCE(%s,target_audience),
                publishing_objective=COALESCE(%s,publishing_objective),primary_channel=COALESCE(%s,primary_channel),
                desired_audience_action=COALESCE(%s,desired_audience_action),
                clarification_history=clarification_history || %s::jsonb,updated_at=NOW()
                WHERE workspace_id=%s AND task_id=%s""",
                (
                    updates.get("topic"), updates.get("brand_id"), updates.get("product_id"),
                    updates.get("target_audience"), updates.get("publishing_objective"),
                    getattr(updates.get("primary_channel"), "value", updates.get("primary_channel")),
                    updates.get("desired_audience_action"), json.dumps(history), principal.workspace_id, task_id,
                ),
            )
            await connection.execute(
                """UPDATE idempotency_records SET response_status=200,
                response_body=%s,updated_at=NOW()
                WHERE workspace_id=%s AND actor_id=%s AND action='answer_clarification' AND idempotency_key=%s""",
                (json.dumps({"task_id": task_id}), principal.workspace_id, principal.user_id, idempotency_key),
            )
            return self._lease(lease_owner, 1)

    async def list_tasks(self, principal: Principal) -> list[dict]:
        async with self._pool.connection() as connection:
            await self._scope(connection, principal.workspace_id)
            await self._require_active_member(connection, principal)
            cursor = await connection.execute(
                """SELECT task_id,workspace_id,user_id,title,status,selected_channels,current_node,error,cancellation_requested
                FROM content_tasks WHERE workspace_id=%s ORDER BY updated_at DESC LIMIT 100""",
                (principal.workspace_id,),
            )
            return [
                {key: str(value) if key in {"task_id", "workspace_id"} else value for key, value in row.items()}
                for row in await cursor.fetchall()
            ]

    async def cancel_task(self, principal: Principal, task_id: str, idempotency_key: str) -> dict:
        request_hash = hashlib.sha256(f"cancel:{task_id}".encode()).hexdigest()
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, principal.workspace_id)
            await self._require_operator(connection, principal)
            inserted = await connection.execute(
                """INSERT INTO idempotency_records
                (workspace_id,actor_id,action,immutable_target,idempotency_key,request_hash,status,expires_at)
                VALUES(%s,%s,'cancel_task',%s,%s,%s,'started',NOW()+INTERVAL '24 hours')
                ON CONFLICT (workspace_id,actor_id,action,idempotency_key) DO NOTHING
                RETURNING idempotency_record_id""",
                (principal.workspace_id, principal.user_id, task_id, idempotency_key, request_hash),
            )
            if await inserted.fetchone() is None:
                existing_cursor = await connection.execute(
                    "SELECT request_hash,status,response_body FROM idempotency_records WHERE workspace_id=%s AND actor_id=%s AND action='cancel_task' AND idempotency_key=%s FOR UPDATE",
                    (principal.workspace_id, principal.user_id, idempotency_key),
                )
                existing = await existing_cursor.fetchone()
                if existing["request_hash"] != request_hash:
                    raise RepositoryConflict("Idempotency key request hash mismatch")
                if existing["status"] == "succeeded" and existing["response_body"]:
                    return existing["response_body"]
                raise RepositoryConflict("Idempotent request is already in progress")
            cursor = await connection.execute(
                "UPDATE content_tasks SET cancellation_requested=TRUE,status='cancelled',updated_at=NOW() WHERE workspace_id=%s AND task_id=%s AND status NOT IN ('completed','cancelled') RETURNING task_id,status",
                (principal.workspace_id, task_id),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RepositoryConflict("Task cannot be cancelled")
            result = {"task_id": str(row["task_id"]), "status": row["status"]}
            await connection.execute(
                "INSERT INTO task_events(workspace_id,task_id,event_type,public_payload,workflow_node,request_id) VALUES(%s,%s,'cancelled',%s,'cancel_task',%s)",
                (principal.workspace_id, task_id, json.dumps({"status": "cancelled", "saved_work_safe": True}), f"cancel:{idempotency_key}"),
            )
            await connection.execute(
                "UPDATE idempotency_records SET status='succeeded',response_status=200,response_body=%s,updated_at=NOW() WHERE workspace_id=%s AND actor_id=%s AND action='cancel_task' AND idempotency_key=%s",
                (json.dumps(result), principal.workspace_id, principal.user_id, idempotency_key),
            )
            return result

    async def get_events(self, principal: Principal, task_id: str, after_event_id: int) -> list[dict]:
        async with self._pool.connection() as connection:
            await self._scope(connection, principal.workspace_id)
            await self._require_active_member(connection, principal)
            task_cursor = await connection.execute(
                "SELECT 1 FROM content_tasks WHERE workspace_id=%s AND task_id=%s",
                (principal.workspace_id, task_id),
            )
            if await task_cursor.fetchone() is None:
                raise RepositoryNotFound("Task not found")
            cursor = await connection.execute(
                """SELECT event_id,event_type,public_payload,workflow_node,created_at
                FROM task_events WHERE workspace_id=%s AND task_id=%s AND event_id>%s
                ORDER BY event_id ASC LIMIT 500""",
                (principal.workspace_id, task_id, after_event_id),
            )
            return list(await cursor.fetchall())

    async def claim_retry(self, principal: Principal, task_id: str, idempotency_key: str) -> WorkflowLease | None:
        request_hash = hashlib.sha256(f"retry:{task_id}".encode()).hexdigest()
        lease_owner = str(uuid4())
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, principal.workspace_id)
            await self._require_operator(connection, principal)
            inserted = await connection.execute(
                """INSERT INTO idempotency_records
                (workspace_id,actor_id,action,immutable_target,idempotency_key,request_hash,status,
                 lease_owner,lease_version,lease_expires_at,expires_at)
                VALUES(%s,%s,'retry_task',%s,%s,%s,'started',%s,1,
                       NOW()+(%s * INTERVAL '1 second'),NOW()+INTERVAL '24 hours')
                ON CONFLICT (workspace_id,actor_id,action,idempotency_key) DO NOTHING
                RETURNING idempotency_record_id""",
                (principal.workspace_id, principal.user_id, task_id, idempotency_key, request_hash, lease_owner, self._lease_seconds),
            )
            if await inserted.fetchone() is None:
                existing_cursor = await connection.execute(
                    """SELECT request_hash,status,
                              lease_owner,lease_version,lease_expires_at<=NOW() AS lease_expired
                    FROM idempotency_records
                    WHERE workspace_id=%s AND actor_id=%s AND action='retry_task' AND idempotency_key=%s FOR UPDATE""",
                    (principal.workspace_id, principal.user_id, idempotency_key),
                )
                existing = await existing_cursor.fetchone()
                if existing["request_hash"] != request_hash:
                    raise RepositoryConflict("Idempotency key request hash mismatch")
                if existing["status"] == "succeeded":
                    return None
                if not existing["lease_expired"]:
                    raise RepositoryConflict("Idempotent request is already in progress")
                task_cursor = await connection.execute(
                    "SELECT status,error FROM content_tasks WHERE workspace_id=%s AND task_id=%s FOR UPDATE",
                    (principal.workspace_id, task_id),
                )
                task = await task_cursor.fetchone()
                error = task["error"] if task else None
                if task is None:
                    raise RepositoryNotFound("Task not found")
                if task["status"] != "failed" or not isinstance(error, dict) or not error.get("recoverable"):
                    await connection.execute(
                        """UPDATE idempotency_records SET status='succeeded',updated_at=NOW()
                        WHERE workspace_id=%s AND actor_id=%s AND action='retry_task' AND idempotency_key=%s""",
                        (principal.workspace_id, principal.user_id, idempotency_key),
                    )
                    return None
                await connection.execute(
                    """UPDATE idempotency_records SET lease_owner=%s,lease_version=lease_version+1,
                        lease_expires_at=NOW()+(%s * INTERVAL '1 second'),updated_at=NOW()
                    WHERE workspace_id=%s AND actor_id=%s AND action='retry_task' AND idempotency_key=%s""",
                    (lease_owner, self._lease_seconds, principal.workspace_id, principal.user_id, idempotency_key),
                )
                version_cursor = await connection.execute(
                    "SELECT lease_version FROM idempotency_records WHERE workspace_id=%s AND actor_id=%s AND action='retry_task' AND idempotency_key=%s",
                    (principal.workspace_id, principal.user_id, idempotency_key),
                )
                return self._lease(lease_owner, (await version_cursor.fetchone())["lease_version"])
            task_cursor = await connection.execute(
                "SELECT status,error FROM content_tasks WHERE workspace_id=%s AND task_id=%s FOR UPDATE",
                (principal.workspace_id, task_id),
            )
            task = await task_cursor.fetchone()
            error = task["error"] if task else None
            if task is None:
                raise RepositoryNotFound("Task not found")
            if task["status"] != "failed" or not isinstance(error, dict) or not error.get("recoverable"):
                raise RepositoryConflict("Task does not have a recoverable failure")
            await connection.execute(
                "INSERT INTO task_events(workspace_id,task_id,event_type,public_payload,workflow_node,request_id) VALUES(%s,%s,'recovery_requested',%s,'retry_task',%s)",
                (principal.workspace_id, task_id, json.dumps({"status": "failed"}), f"retry:{idempotency_key}"),
            )
            await connection.execute(
                """UPDATE idempotency_records SET response_status=202,response_body=%s,updated_at=NOW()
                WHERE workspace_id=%s AND actor_id=%s AND action='retry_task' AND idempotency_key=%s""",
                (json.dumps({"task_id": task_id}), principal.workspace_id, principal.user_id, idempotency_key),
            )
            return self._lease(lease_owner, 1)
