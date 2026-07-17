from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent_api.domain.models import Channel
from agent_api.domain.errors import ConflictError
from agent_api.repositories.leases import WorkflowLease, current_lease


class PostgresChannelStore:
    def __init__(self, database_url: str, *, lease_seconds: float = 180) -> None:
        self._pool = AsyncConnectionPool(database_url, open=False, kwargs={"row_factory": dict_row})
        self._lease_seconds = lease_seconds

    async def open(self) -> None:
        await self._pool.open()

    async def close(self) -> None:
        await self._pool.close()

    async def _scope(self, connection, workspace_id: str) -> None:
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))

    def _lease(self, owner: str, version: int) -> WorkflowLease:
        return WorkflowLease(owner=owner, version=version, heartbeat_seconds=max(0.05, self._lease_seconds / 3))

    async def _assert_active_lease(self, connection) -> None:
        context = current_lease()
        if context is None:
            return
        cursor = await connection.execute(
            """SELECT 1 FROM idempotency_records WHERE workspace_id=%s AND actor_id=%s AND action=%s
              AND idempotency_key=%s AND status='started' AND lease_owner=%s AND lease_version=%s
              AND lease_expires_at>NOW()""",
            (context.workspace_id, context.actor_id, context.action, context.idempotency_key, context.lease.owner, context.lease.version),
        )
        if await cursor.fetchone() is None:
            raise ConflictError("Channel operation lease was lost")

    async def claim_operation(self, workspace_id: str, actor_id: str, action: str, idempotency_key: str, target: str, request: dict) -> tuple[WorkflowLease | None, dict | None]:
        request_hash = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        owner = str(uuid4())
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            inserted = await connection.execute(
                """INSERT INTO idempotency_records
                (workspace_id,actor_id,action,immutable_target,idempotency_key,request_hash,status,lease_owner,lease_version,lease_expires_at,expires_at)
                VALUES(%s,%s,%s,%s,%s,%s,'started',%s,1,NOW()+(%s * INTERVAL '1 second'),NOW()+INTERVAL '24 hours')
                ON CONFLICT (workspace_id,actor_id,action,idempotency_key) DO NOTHING RETURNING idempotency_record_id""",
                (workspace_id, actor_id, action, target, idempotency_key, request_hash, owner, self._lease_seconds),
            )
            if await inserted.fetchone() is not None:
                return self._lease(owner, 1), None
            existing_cursor = await connection.execute(
                """SELECT request_hash,status,response_body,lease_version,lease_expires_at<=NOW() AS lease_expired
                FROM idempotency_records WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s FOR UPDATE""",
                (workspace_id, actor_id, action, idempotency_key),
            )
            existing = await existing_cursor.fetchone()
            if existing["request_hash"] != request_hash:
                raise ConflictError("Idempotency key request mismatch")
            if existing["status"] == "succeeded":
                return None, existing["response_body"]
            if not existing["lease_expired"]:
                raise ConflictError("Idempotent channel operation is already in progress")
            version = int(existing["lease_version"]) + 1
            await connection.execute(
                """UPDATE idempotency_records SET lease_owner=%s,lease_version=%s,
                  lease_expires_at=NOW()+(%s * INTERVAL '1 second'),updated_at=NOW()
                WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s""",
                (owner, version, self._lease_seconds, workspace_id, actor_id, action, idempotency_key),
            )
            return self._lease(owner, version), None

    async def renew_operation(self, workspace_id: str, actor_id: str, action: str, idempotency_key: str, lease: WorkflowLease) -> bool:
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """UPDATE idempotency_records SET lease_expires_at=NOW()+(%s * INTERVAL '1 second'),updated_at=NOW()
                WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s
                  AND status='started' AND lease_owner=%s AND lease_version=%s RETURNING idempotency_record_id""",
                (self._lease_seconds, workspace_id, actor_id, action, idempotency_key, lease.owner, lease.version),
            )
            return await cursor.fetchone() is not None

    async def complete_operation(self, workspace_id: str, actor_id: str, action: str, idempotency_key: str, response: dict, lease: WorkflowLease) -> None:
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """UPDATE idempotency_records SET status='succeeded',response_status=200,response_body=%s,updated_at=NOW()
                WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s
                  AND status='started' AND lease_owner=%s AND lease_version=%s RETURNING idempotency_record_id""",
                (json.dumps(response), workspace_id, actor_id, action, idempotency_key, lease.owner, lease.version),
            )
            if await cursor.fetchone() is None:
                raise ConflictError("Channel operation lease was lost before completion")

    async def task_context(self, workspace_id: str, task_id: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT t.selected_channels,b.product_id FROM content_tasks t
                JOIN content_briefs b ON b.workspace_id=t.workspace_id AND b.task_id=t.task_id
                WHERE t.workspace_id=%s AND t.task_id=%s""",
                (workspace_id, task_id),
            )
            row = await cursor.fetchone()
            return {**row, "product_id": str(row["product_id"])} if row and row["product_id"] else row

    async def workspace_snapshot(self, workspace_id: str, task_id: str) -> dict:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            brief_cursor = await connection.execute("SELECT * FROM content_briefs WHERE workspace_id=%s AND task_id=%s", (workspace_id, task_id))
            versions_cursor = await connection.execute(
                """SELECT content_version_id,content_type,channel,version_number,parent_version_id,master_content_version_id,
                          content,review_status,approval_status,immutable_hash,created_by_type,created_by_id,prompt_version,change_summary,created_at
                FROM content_versions WHERE workspace_id=%s AND task_id=%s ORDER BY created_at""", (workspace_id, task_id),
            )
            reviews_cursor = await connection.execute(
                """SELECT review_id,content_version_id,review_type,passed,max_severity,revision_instructions,reviewer_type,reviewer_version,created_at
                FROM review_results WHERE workspace_id=%s AND task_id=%s ORDER BY created_at""", (workspace_id, task_id),
            )
            issues_cursor = await connection.execute(
                """SELECT i.issue_id,i.review_id,i.issue_type,i.severity,i.problematic_text,i.reason,i.supporting_fact_ids,
                          i.missing_evidence,i.suggested_action,i.target_block_id,i.status,i.created_at
                FROM review_issues i WHERE i.workspace_id=%s AND i.task_id=%s ORDER BY i.created_at""", (workspace_id, task_id),
            )
            approvals_cursor = await connection.execute(
                """SELECT approval_requirement_id,content_version_id,decision_type,required_role,status,target_snapshot_hash,created_at
                FROM approval_requirements WHERE workspace_id=%s AND task_id=%s ORDER BY created_at""", (workspace_id, task_id),
            )
            decisions_cursor = await connection.execute(
                """SELECT decision_id,content_version_id,approval_requirement_id,decision_type,decision,comment,user_id,user_role,target_snapshot_hash,created_at
                FROM human_decisions WHERE workspace_id=%s AND task_id=%s ORDER BY created_at""", (workspace_id, task_id),
            )
            tools_cursor = await connection.execute(
                """SELECT tool_call_id,workflow_node,mcp_server,tool_name,capability,output_status,latency_ms,error_code,
                          error_summary,approval_result,target_snapshot_hash,created_at
                FROM tool_call_logs WHERE workspace_id=%s AND task_id=%s ORDER BY created_at""", (workspace_id, task_id),
            )
            lineage_cursor = await connection.execute(
                """SELECT lineage_id,fact_id,master_content_version_id,master_block_id,channel_variant_id,channel_block_id,transformation_type,status,created_at
                FROM content_lineage WHERE workspace_id=%s AND task_id=%s ORDER BY created_at""", (workspace_id, task_id),
            )
            def serialize(row: dict) -> dict:
                return {key: str(value) if key.endswith("_id") and value is not None else value for key, value in row.items()}
            brief = await brief_cursor.fetchone()
            return {
                "brief": serialize(brief) if brief else None,
                "versions": [serialize(row) for row in await versions_cursor.fetchall()],
                "reviews": [serialize(row) for row in await reviews_cursor.fetchall()],
                "issues": [serialize(row) for row in await issues_cursor.fetchall()],
                "approval_requirements": [serialize(row) for row in await approvals_cursor.fetchall()],
                "human_decisions": [serialize(row) for row in await decisions_cursor.fetchall()],
                "tool_calls": [serialize(row) for row in await tools_cursor.fetchall()],
                "lineage": [serialize(row) for row in await lineage_cursor.fetchall()],
            }

    async def set_task_stage(self, workspace_id: str, task_id: str, status: str, node: str, event_type: str, payload: dict) -> None:
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            await self._assert_active_lease(connection)
            await connection.execute(
                "UPDATE content_tasks SET status=%s,current_node=%s,updated_at=NOW() WHERE workspace_id=%s AND task_id=%s",
                (status, node, workspace_id, task_id),
            )
            await connection.execute(
                """INSERT INTO task_events(workspace_id,task_id,event_type,public_payload,workflow_node,request_id)
                VALUES(%s,%s,%s,%s,%s,%s)""",
                (workspace_id, task_id, event_type, json.dumps(payload), node, f"channel:{uuid4()}"),
            )

    async def approved_master(self, workspace_id: str, task_id: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT v.content_version_id,v.content,v.immutable_hash,'approved' AS approval_status
                FROM content_versions v WHERE v.workspace_id=%s AND v.task_id=%s
                  AND v.content_type IN ('master_draft','master_revised','master_approved')
                  AND (SELECT COUNT(DISTINCT r.decision_type) FROM approval_requirements r
                       WHERE r.workspace_id=v.workspace_id AND r.task_id=v.task_id
                         AND r.content_version_id=v.content_version_id AND r.status='satisfied'
                         AND r.decision_type IN ('master_brand','master_final'))=2
                ORDER BY v.created_at DESC LIMIT 1""",
                (workspace_id, task_id),
            )
            row = await cursor.fetchone()
            return {**row, "content_version_id": str(row["content_version_id"])} if row else None

    async def channel_specs(self, workspace_id: str, channels: list[Channel]) -> dict[str, dict]:
        values = [channel.value for channel in channels]
        if not values:
            return {}
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT DISTINCT ON (channel) channel,version,length_rules,required_fields,tone,cta_style,hashtag_rules,forbidden_patterns
                FROM channel_spec_versions WHERE workspace_id=%s AND channel=ANY(%s) AND active=TRUE
                ORDER BY channel,created_at DESC""",
                (workspace_id, values),
            )
            return {row["channel"]: row for row in await cursor.fetchall()}

    async def save_variant(self, **payload) -> str:
        workspace_id = payload["workspace_id"]
        task_id = payload["task_id"]
        channel = payload["channel"]
        master_version_id = payload["master_content_version_id"]
        content = payload["content"]
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        version_id = str(uuid4())
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            await self._assert_active_lease(connection)
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"final-gate:{workspace_id}:{task_id}",),
            )
            master_cursor = await connection.execute(
                """SELECT v.immutable_hash FROM content_versions v
                WHERE v.workspace_id=%s AND v.task_id=%s AND v.content_version_id=%s
                  AND v.immutable_hash=%s
                  AND (SELECT COUNT(DISTINCT r.decision_type) FROM approval_requirements r
                       WHERE r.workspace_id=v.workspace_id AND r.task_id=v.task_id
                         AND r.content_version_id=v.content_version_id AND r.status='satisfied'
                         AND r.decision_type IN ('master_brand','master_final'))=2
                FOR SHARE OF v""",
                (workspace_id, task_id, master_version_id, payload["master_snapshot_hash"]),
            )
            if await master_cursor.fetchone() is None:
                raise ValueError("Approved canonical master changed before channel persistence")
            await connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"channel:{workspace_id}:{task_id}:{channel}",))
            content_type = payload.get("content_type", "channel_draft")
            number_cursor = await connection.execute(
                """SELECT COALESCE(MAX(version_number),0)+1 AS number FROM content_versions
                WHERE workspace_id=%s AND task_id=%s AND content_type=%s AND channel=%s""",
                (workspace_id, task_id, content_type, channel),
            )
            version_number = (await number_cursor.fetchone())["number"]
            await connection.execute(
                """INSERT INTO content_versions
                (content_version_id,workspace_id,task_id,content_type,channel,version_number,parent_version_id,master_content_version_id,
                 content,structured_blocks,immutable_hash,created_by_type,created_by_id,prompt_version,change_summary)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'model',%s,%s,%s)""",
                (version_id, workspace_id, task_id, content_type, channel, version_number, payload.get("parent_version_id"), master_version_id, content,
                 json.dumps({"claims": payload["claims"], "block_mappings": payload["block_mappings"], "spec_version": payload["spec_version"]}),
                 content_hash, payload["actor_id"], f"channel-{channel}-v1", f"Derived from approved master {master_version_id}"),
            )
            if payload.get("parent_version_id"):
                await connection.execute(
                    """UPDATE approval_requirements SET status='invalidated',invalidated_at=NOW(),
                      invalidation_reason='Superseded by targeted channel revision'
                    WHERE workspace_id=%s AND task_id=%s AND content_version_id=%s AND status IN ('pending','satisfied')""",
                    (workspace_id, task_id, payload["parent_version_id"]),
                )
            master_block_cursor = await connection.execute(
                """SELECT block_id FROM content_blocks WHERE workspace_id=%s AND task_id=%s AND content_version_id=%s ORDER BY position LIMIT 1""",
                (workspace_id, task_id, master_version_id),
            )
            master_block = await master_block_cursor.fetchone()
            if master_block is None:
                master_content_cursor = await connection.execute(
                    "SELECT content FROM content_versions WHERE workspace_id=%s AND task_id=%s AND content_version_id=%s",
                    (workspace_id, task_id, master_version_id),
                )
                master_content = (await master_content_cursor.fetchone())["content"]
                master_block_id = str(uuid4())
                await connection.execute(
                    """INSERT INTO content_blocks
                    (block_id,workspace_id,task_id,content_version_id,block_type,position,content,content_hash)
                    VALUES(%s,%s,%s,%s,'body',0,%s,%s)""",
                    (master_block_id, workspace_id, task_id, master_version_id, master_content, hashlib.sha256(master_content.encode()).hexdigest()),
                )
            else:
                master_block_id = str(master_block["block_id"])
            channel_block_id = str(uuid4())
            await connection.execute(
                """INSERT INTO content_blocks
                (block_id,workspace_id,task_id,content_version_id,block_type,position,content,content_hash,metadata)
                VALUES(%s,%s,%s,%s,'body',0,%s,%s,%s)""",
                (channel_block_id, workspace_id, task_id, version_id, content, content_hash, json.dumps({"spec_version": payload["spec_version"]})),
            )
            transformation = "style_adaptation"
            if payload["block_mappings"]:
                transformation = str(payload["block_mappings"][0].get("transformation_type") or transformation)
            await connection.execute(
                """INSERT INTO content_lineage
                (workspace_id,task_id,master_content_version_id,master_block_id,channel_variant_id,channel_block_id,transformation_type,status)
                VALUES(%s,%s,%s,%s,%s,%s,%s,'supported')""",
                (workspace_id, task_id, master_version_id, master_block_id, version_id, channel_block_id, transformation),
            )
        return version_id

    async def current_variant(self, workspace_id: str, task_id: str, channel: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT content_version_id,master_content_version_id,content,immutable_hash FROM content_versions
                WHERE workspace_id=%s AND task_id=%s AND channel=%s
                ORDER BY created_at DESC LIMIT 1""",
                (workspace_id, task_id, channel),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return {**row, "content_version_id": str(row["content_version_id"]), "master_content_version_id": str(row["master_content_version_id"])}

    async def persist_reviews(self, **payload) -> None:
        review_type = {"format": "channel_format", "facts": "factual", "brand": "brand", "compliance": "compliance"}
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, payload["workspace_id"])
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"final-gate:{payload['workspace_id']}:{payload['task_id']}",),
            )
            await self._assert_active_lease(connection)
            for key, review in payload["reviews"].items():
                review_id = str(uuid4())
                issues = [str(issue) for issue in review.get("issues", [])]
                await connection.execute(
                    """INSERT INTO review_results
                    (review_id,workspace_id,task_id,content_version_id,review_type,passed,max_severity,revision_instructions,reviewer_type,reviewer_version)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'deterministic','channel-review-v1')""",
                    (review_id, payload["workspace_id"], payload["task_id"], payload["content_version_id"], review_type[key], bool(review.get("passed")), None if review.get("passed") else "critical", json.dumps([f"Resolve {issue}" for issue in issues])),
                )
                for issue in issues:
                    await connection.execute(
                        """INSERT INTO review_issues
                        (workspace_id,task_id,review_id,issue_type,severity,reason,suggested_action)
                        VALUES(%s,%s,%s,%s,'critical',%s,%s)""",
                        (payload["workspace_id"], payload["task_id"], review_id, review_type[key], issue, f"Resolve {issue}"),
                    )
            if not payload["reviews"]["facts"].get("passed"):
                lineage_cursor = await connection.execute(
                    """SELECT master_content_version_id,master_block_id,channel_block_id FROM content_lineage
                    WHERE workspace_id=%s AND task_id=%s AND channel_variant_id=%s LIMIT 1""",
                    (payload["workspace_id"], payload["task_id"], payload["content_version_id"]),
                )
                lineage = await lineage_cursor.fetchone()
                if lineage:
                    await connection.execute(
                        """INSERT INTO content_lineage
                        (workspace_id,task_id,master_content_version_id,master_block_id,channel_variant_id,channel_block_id,transformation_type,status)
                        VALUES(%s,%s,%s,%s,%s,%s,'style_adaptation','unsupported_new_claim')""",
                        (payload["workspace_id"], payload["task_id"], lineage["master_content_version_id"], lineage["master_block_id"], payload["content_version_id"], lineage["channel_block_id"]),
                    )
            if all(bool(review.get("passed")) for review in payload["reviews"].values()):
                hash_cursor = await connection.execute(
                    "SELECT immutable_hash FROM content_versions WHERE workspace_id=%s AND task_id=%s AND content_version_id=%s",
                    (payload["workspace_id"], payload["task_id"], payload["content_version_id"]),
                )
                content_hash = (await hash_cursor.fetchone())["immutable_hash"]
                await connection.execute(
                    """INSERT INTO approval_requirements
                    (workspace_id,task_id,content_version_id,decision_type,required_role,target_snapshot_hash)
                    VALUES(%s,%s,%s,'channel','brand_reviewer',%s)""",
                    (payload["workspace_id"], payload["task_id"], payload["content_version_id"], content_hash),
                )

    async def approved_channel_versions(self, workspace_id: str, task_id: str) -> dict[str, str]:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """WITH current_versions AS (
                  SELECT DISTINCT ON (channel) workspace_id,task_id,channel,content_version_id
                  FROM content_versions
                  WHERE workspace_id=%s AND task_id=%s AND channel IS NOT NULL
                  ORDER BY channel,version_number DESC,created_at DESC
                )
                SELECT v.channel,v.content_version_id FROM current_versions v
                JOIN approval_requirements r
                  ON r.workspace_id=v.workspace_id AND r.task_id=v.task_id
                 AND r.content_version_id=v.content_version_id
                WHERE r.decision_type='channel' AND r.status='satisfied'""",
                (workspace_id, task_id),
            )
            return {row["channel"]: str(row["content_version_id"]) for row in await cursor.fetchall()}

    async def open_critical_issues(self, workspace_id: str, task_id: str) -> list[dict]:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT i.issue_id,i.issue_type,i.reason FROM review_issues i
                WHERE i.workspace_id=%s AND i.task_id=%s AND i.severity='critical' AND i.status='open'""",
                (workspace_id, task_id),
            )
            return [{**row, "issue_id": str(row["issue_id"])} for row in await cursor.fetchall()]

    async def unsupported_lineage(self, workspace_id: str, task_id: str) -> list[dict]:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT lineage_id,channel_variant_id FROM content_lineage
                WHERE workspace_id=%s AND task_id=%s AND status='unsupported_new_claim'""",
                (workspace_id, task_id),
            )
            return [{**row, "lineage_id": str(row["lineage_id"]), "channel_variant_id": str(row["channel_variant_id"])} for row in await cursor.fetchall()]

    async def cross_channel_conflicts(self, workspace_id: str, task_id: str, channel_versions: dict[str, str]) -> list[dict]:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT channel,master_content_version_id FROM content_versions
                WHERE workspace_id=%s AND task_id=%s AND content_version_id=ANY(%s)""",
                (workspace_id, task_id, list(channel_versions.values())),
            )
            rows = await cursor.fetchall()
            roots = {str(row["master_content_version_id"]) for row in rows}
            channels = {row["channel"] for row in rows}
            if len(roots) == 1 and channels == set(channel_versions):
                return []
            return [{"type": "master_lineage_mismatch", "channels": sorted(channels), "master_versions": sorted(roots)}]

    async def create_final_requirement(self, **payload) -> dict:
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, payload["workspace_id"])
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"final-gate:{payload['workspace_id']}:{payload['task_id']}",),
            )
            channel_ids = list(payload["channel_versions"].values())
            current_cursor = await connection.execute(
                """WITH current_ids AS (
                  SELECT DISTINCT ON (channel) channel,content_version_id
                  FROM content_versions
                  WHERE workspace_id=%s AND task_id=%s AND channel IS NOT NULL
                  ORDER BY channel,version_number DESC,created_at DESC
                )
                SELECT v.channel,v.content_version_id FROM current_ids c
                JOIN content_versions v
                  ON v.workspace_id=%s AND v.task_id=%s AND v.content_version_id=c.content_version_id
                JOIN approval_requirements r
                  ON r.workspace_id=v.workspace_id AND r.task_id=v.task_id
                 AND r.content_version_id=v.content_version_id
                WHERE r.decision_type='channel' AND r.status='satisfied'
                FOR SHARE OF v,r""",
                (payload["workspace_id"], payload["task_id"], payload["workspace_id"], payload["task_id"]),
            )
            current_approved = {
                row["channel"]: str(row["content_version_id"])
                for row in await current_cursor.fetchall()
            }
            if current_approved != payload["channel_versions"]:
                raise ValueError("Current channel approval set changed during final gate validation")
            roots_cursor = await connection.execute(
                """SELECT master_content_version_id FROM content_versions
                WHERE workspace_id=%s AND task_id=%s AND content_version_id=ANY(%s) FOR SHARE""",
                (payload["workspace_id"], payload["task_id"], channel_ids),
            )
            roots = {str(row["master_content_version_id"]) for row in await roots_cursor.fetchall()}
            if len(roots) != 1:
                raise ValueError("Approved channels do not share one canonical master version")
            master_version_id = next(iter(roots))
            manifest_ids = [master_version_id, *channel_ids]
            package_cursor = await connection.execute(
                """SELECT v.content_version_id,v.content_type,v.channel,v.immutable_hash
                FROM content_versions v WHERE v.workspace_id=%s AND v.task_id=%s AND v.content_version_id=ANY(%s)
                  AND (v.channel IS NOT NULL OR (v.content_version_id=%s AND
                    (SELECT COUNT(DISTINCT r.decision_type) FROM approval_requirements r
                     WHERE r.workspace_id=v.workspace_id AND r.task_id=v.task_id
                       AND r.content_version_id=v.content_version_id AND r.status='satisfied'
                       AND r.decision_type IN ('master_brand','master_final'))=2))
                ORDER BY v.content_type,v.channel,v.version_number FOR SHARE OF v""",
                (payload["workspace_id"], payload["task_id"], manifest_ids, master_version_id),
            )
            versions = [
                {"content_version_id": str(row["content_version_id"]), "content_type": row["content_type"], "channel": row["channel"], "immutable_hash": row["immutable_hash"]}
                for row in await package_cursor.fetchall()
            ]
            if len(versions) != len(manifest_ids) or len([version for version in versions if version["channel"]]) != len(payload["channel_versions"]):
                raise ValueError("Approved channel package changed during final gate validation")
            gate_cursor = await connection.execute(
                """SELECT t.selected_channels,
                  (SELECT COUNT(*) FROM review_issues i WHERE i.workspace_id=t.workspace_id AND i.task_id=t.task_id AND i.severity='critical' AND i.status='open') AS critical_count,
                  (SELECT COUNT(*) FROM content_lineage l WHERE l.workspace_id=t.workspace_id AND l.task_id=t.task_id AND l.status='unsupported_new_claim') AS unsupported_count,
                  (SELECT COUNT(DISTINCT v.master_content_version_id) FROM content_versions v WHERE v.workspace_id=t.workspace_id AND v.task_id=t.task_id AND v.content_version_id=ANY(%s)) AS master_root_count,
                  (SELECT g.version FROM content_briefs b JOIN brand_guideline_versions g ON g.workspace_id=b.workspace_id AND g.brand_id=b.brand_id AND g.active=TRUE WHERE b.workspace_id=t.workspace_id AND b.task_id=t.task_id ORDER BY g.created_at DESC LIMIT 1) AS brand_guideline_version
                FROM content_tasks t WHERE t.workspace_id=%s AND t.task_id=%s FOR SHARE OF t""",
                (list(payload["channel_versions"].values()), payload["workspace_id"], payload["task_id"]),
            )
            gate = await gate_cursor.fetchone()
            if not gate or gate["critical_count"] or gate["unsupported_count"] or gate["master_root_count"] != 1:
                raise ValueError("Final package no longer satisfies critical issue, factual lineage, or canonical master gates")
            required_channels = sorted(gate["selected_channels"])
            if required_channels != sorted(payload["channel_versions"]):
                raise ValueError("Required channel set changed during final gate validation")
            spec_cursor = await connection.execute(
                "SELECT channel,version FROM channel_spec_versions WHERE workspace_id=%s AND channel=ANY(%s) AND active=TRUE ORDER BY channel",
                (payload["workspace_id"], required_channels),
            )
            spec_versions = {row["channel"]: row["version"] for row in await spec_cursor.fetchall()}
            fact_cursor = await connection.execute(
                """SELECT f.fact_id,f.version FROM content_briefs b JOIN verified_facts f
                  ON f.workspace_id=b.workspace_id AND f.product_id=b.product_id
                WHERE b.workspace_id=%s AND b.task_id=%s AND f.status='active' AND f.public_usage_allowed=TRUE
                  AND (f.effective_at IS NULL OR f.effective_at<=NOW()) AND (f.expires_at IS NULL OR f.expires_at>NOW())
                ORDER BY f.fact_id""",
                (payload["workspace_id"], payload["task_id"]),
            )
            fact_versions = [{"fact_id": str(row["fact_id"]), "version": row["version"]} for row in await fact_cursor.fetchall()]
            if set(spec_versions) != set(required_channels) or not gate["brand_guideline_version"] or not fact_versions:
                raise ValueError("Authoritative facts, brand guideline, or channel specification is unavailable")
            snapshot = {"versions": versions, "required_channels": required_channels, "channel_spec_versions": spec_versions, "brand_guideline_version": gate["brand_guideline_version"], "authoritative_fact_versions": fact_versions}
            target_snapshot_hash = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            existing = await connection.execute(
                """SELECT approval_requirement_id,target_snapshot_hash,status FROM approval_requirements
                WHERE workspace_id=%s AND task_id=%s AND decision_type='final_package'
                  AND target_snapshot_hash=%s ORDER BY created_at DESC LIMIT 1""",
                (payload["workspace_id"], payload["task_id"], target_snapshot_hash),
            )
            row = await existing.fetchone()
            if row:
                requirement = {**row, "approval_requirement_id": str(row["approval_requirement_id"])}
            else:
                requirement_id = str(uuid4())
                await connection.execute(
                    """INSERT INTO approval_requirements
                    (approval_requirement_id,workspace_id,task_id,decision_type,required_role,target_snapshot_hash)
                    VALUES(%s,%s,%s,'final_package','final_approver',%s)""",
                    (requirement_id, payload["workspace_id"], payload["task_id"], target_snapshot_hash),
                )
                requirement = {"approval_requirement_id": requirement_id, "target_snapshot_hash": target_snapshot_hash, "status": "pending"}
            manifest = {"content_version_ids": manifest_ids, "snapshot": snapshot}
            await connection.execute(
                """INSERT INTO idempotency_records
                (workspace_id,actor_id,action,immutable_target,idempotency_key,request_hash,status,response_status,response_body,expires_at)
                VALUES(%s,'system','final_package_manifest',%s,%s,%s,'succeeded',200,%s,NOW()+INTERVAL '365 days')
                ON CONFLICT (workspace_id,actor_id,action,idempotency_key) DO NOTHING""",
                (payload["workspace_id"], target_snapshot_hash, target_snapshot_hash, target_snapshot_hash, json.dumps(manifest)),
            )
            return requirement
