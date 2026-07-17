from __future__ import annotations

import hashlib
import json
import asyncio
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .exports import render_package


class ToolRejected(RuntimeError):
    pass


class BrandToolsRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._pool: AsyncConnectionPool | None = None
        self._session_count = 0
        self._lifecycle_lock = asyncio.Lock()

    async def open(self) -> None:
        async with self._lifecycle_lock:
            if self._pool is None:
                self._pool = AsyncConnectionPool(self._database_url, open=False, kwargs={"row_factory": dict_row})
                await self._pool.open()
            self._session_count += 1

    async def close(self) -> None:
        async with self._lifecycle_lock:
            self._session_count = max(0, self._session_count - 1)
            if self._session_count == 0 and self._pool is not None:
                await self._pool.close()
                self._pool = None

    def _require_pool(self) -> AsyncConnectionPool:
        if self._pool is None:
            raise RuntimeError("MCP repository is not ready")
        return self._pool

    async def _scope(self, connection, workspace_id: str) -> None:
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))

    async def search_documents(self, workspace_id: str, query: str, limit: int) -> list[dict]:
        async with self._require_pool().connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT document_id,document_name,document_type,version,authority_level,status
                FROM source_documents WHERE workspace_id=%s AND status='active'
                  AND (document_name ILIKE %s OR metadata::text ILIKE %s)
                ORDER BY CASE authority_level WHEN 'primary' THEN 1 WHEN 'approved' THEN 2 ELSE 3 END
                LIMIT %s""",
                (workspace_id, f"%{query}%", f"%{query}%", limit),
            )
            return [{**row, "document_id": str(row["document_id"])} for row in await cursor.fetchall()]

    async def product_facts(self, workspace_id: str, product_id: str) -> list[dict]:
        async with self._require_pool().connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT fact_id,fact_content,source_document_id,version,authority_level,effective_at,expires_at
                FROM verified_facts WHERE workspace_id=%s AND product_id=%s AND status='active'
                  AND public_usage_allowed=TRUE
                  AND (effective_at IS NULL OR effective_at<=NOW())
                  AND (expires_at IS NULL OR expires_at>NOW())
                ORDER BY CASE authority_level WHEN 'primary' THEN 1 WHEN 'approved' THEN 2 ELSE 3 END""",
                (workspace_id, product_id),
            )
            return [
                {**row, "fact_id": str(row["fact_id"]), "source_document_id": str(row["source_document_id"])}
                for row in await cursor.fetchall()
            ]

    async def brand_guidelines(self, workspace_id: str, brand_id: str) -> dict | None:
        async with self._require_pool().connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT guideline_version_id,version,positioning,standard_terms,tone,required_language,
                          forbidden_expressions,cta_guidance
                FROM brand_guideline_versions WHERE workspace_id=%s AND brand_id=%s AND active=TRUE
                  AND (effective_at IS NULL OR effective_at<=NOW())
                  AND (expires_at IS NULL OR expires_at>NOW())
                ORDER BY created_at DESC LIMIT 1""",
                (workspace_id, brand_id),
            )
            row = await cursor.fetchone()
            return {**row, "guideline_version_id": str(row["guideline_version_id"])} if row else None

    async def channel_spec(self, workspace_id: str, channel: str) -> dict | None:
        async with self._require_pool().connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT channel_spec_version_id,channel,version,length_rules,required_fields,tone,cta_style,
                          hashtag_rules,forbidden_patterns
                FROM channel_spec_versions WHERE workspace_id=%s AND channel=%s AND active=TRUE
                ORDER BY created_at DESC LIMIT 1""",
                (workspace_id, channel),
            )
            row = await cursor.fetchone()
            return {**row, "channel_spec_version_id": str(row["channel_spec_version_id"])} if row else None

    async def save_version(
        self,
        workspace_id: str,
        task_id: str,
        content_type: str,
        content: str,
        parent_version_id: str | None,
        actor_id: str,
        idempotency_key: str,
        channel: str | None,
        master_content_version_id: str | None,
    ) -> tuple[dict, bool]:
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        request = {
            "task_id": task_id, "content_type": content_type, "content_hash": content_hash,
            "parent_version_id": parent_version_id, "channel": channel,
            "master_content_version_id": master_content_version_id,
        }
        request_hash = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        async with self._require_pool().connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            await connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"mcp:{workspace_id}:{actor_id}:save:{idempotency_key}",))
            existing_cursor = await connection.execute(
                """SELECT request_hash,status,response_body FROM idempotency_records
                WHERE workspace_id=%s AND actor_id=%s AND action='mcp_save_version' AND idempotency_key=%s FOR UPDATE""",
                (workspace_id, actor_id, idempotency_key),
            )
            existing = await existing_cursor.fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise ToolRejected("Idempotency key request mismatch")
                if existing["status"] == "succeeded" and existing["response_body"]:
                    return existing["response_body"], True
                raise ToolRejected("Idempotent operation is already in progress")
            version_id = str(uuid4())
            await connection.execute(
                """INSERT INTO idempotency_records
                (workspace_id,actor_id,action,immutable_target,idempotency_key,request_hash,status,expires_at)
                VALUES(%s,%s,'mcp_save_version',%s,%s,%s,'started',NOW()+INTERVAL '24 hours')""",
                (workspace_id, actor_id, content_hash, idempotency_key, request_hash),
            )
            await connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"mcp:{workspace_id}:{task_id}:{content_type}:{channel or '-'}",))
            cursor = await connection.execute(
                """SELECT COALESCE(MAX(version_number),0)+1 AS number FROM content_versions
                WHERE workspace_id=%s AND task_id=%s AND content_type=%s AND channel IS NOT DISTINCT FROM %s""",
                (workspace_id, task_id, content_type, channel),
            )
            version_number = (await cursor.fetchone())["number"]
            await connection.execute(
                """INSERT INTO content_versions
                (content_version_id,workspace_id,task_id,content_type,channel,version_number,parent_version_id,master_content_version_id,
                 content,immutable_hash,created_by_type,created_by_id,change_summary)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'workflow',%s,'Saved through MCP')""",
                (version_id, workspace_id, task_id, content_type, channel, version_number, parent_version_id, master_content_version_id, content, content_hash, actor_id),
            )
            result = {"content_version_id": version_id, "immutable_hash": content_hash, "version_number": version_number}
            await connection.execute(
                """UPDATE idempotency_records SET status='succeeded',response_status=200,response_body=%s,updated_at=NOW()
                WHERE workspace_id=%s AND actor_id=%s AND action='mcp_save_version' AND idempotency_key=%s""",
                (json.dumps(result), workspace_id, actor_id, idempotency_key),
            )
            return result, False

    async def authorized_package(
        self, *, workspace_id: str, task_id: str, actor_id: str, decision_id: str,
        target_snapshot_hash: str, idempotency_key: str, action: str,
        allowed_types: tuple[str, ...], formats: list[str],
    ) -> tuple[dict, bool]:
        request = {
            "task_id": task_id, "decision_id": decision_id,
            "target_snapshot_hash": target_snapshot_hash, "formats": sorted(set(formats)),
        }
        request_hash = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        async with self._require_pool().connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            await connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"mcp:{workspace_id}:{actor_id}:{action}:{idempotency_key}",))
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"final-gate:{workspace_id}:{task_id}",),
            )
            existing_cursor = await connection.execute(
                """SELECT request_hash,status,response_body FROM idempotency_records
                WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s FOR UPDATE""",
                (workspace_id, actor_id, action, idempotency_key),
            )
            existing = await existing_cursor.fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise ToolRejected("Idempotency key request mismatch")
                if existing["status"] == "succeeded" and existing["response_body"]:
                    return existing["response_body"], True
                raise ToolRejected("Idempotent operation is already in progress")
            decision_cursor = await connection.execute(
                """SELECT d.decision,d.decision_type,d.target_snapshot_hash,d.user_id,
                          d.approval_requirement_id,r.status
                FROM human_decisions d JOIN approval_requirements r
                  ON r.workspace_id=d.workspace_id AND r.approval_requirement_id=d.approval_requirement_id
                WHERE d.workspace_id=%s AND d.task_id=%s AND d.decision_id=%s
                FOR SHARE OF d,r""",
                (workspace_id, task_id, decision_id),
            )
            decision = await decision_cursor.fetchone()
            if (
                not decision or decision["decision"] not in {"approve", "authorize"}
                or decision["decision_type"] not in allowed_types
                or decision["status"] != "satisfied"
                or decision["target_snapshot_hash"] != target_snapshot_hash
                or decision["user_id"] != actor_id
            ):
                raise ToolRejected("Persisted approval evidence is invalid")
            manifest_cursor = await connection.execute(
                """SELECT response_body FROM idempotency_records
                WHERE workspace_id=%s AND actor_id='system' AND action='final_package_manifest'
                  AND immutable_target=%s AND idempotency_key=%s AND status='succeeded' FOR SHARE""",
                (workspace_id, target_snapshot_hash, target_snapshot_hash),
            )
            manifest_row = await manifest_cursor.fetchone()
            manifest = manifest_row["response_body"] if manifest_row else None
            if not isinstance(manifest, dict) or not isinstance(manifest.get("content_version_ids"), list) or not isinstance(manifest.get("snapshot"), dict):
                raise ToolRejected("Persisted final package manifest is unavailable")
            manifest_ids = [str(version_id) for version_id in manifest["content_version_ids"]]
            package_cursor = await connection.execute(
                """SELECT v.content_version_id,v.content_type,v.channel,v.version_number,v.content,v.immutable_hash
                FROM content_versions v WHERE v.workspace_id=%s AND v.task_id=%s AND v.content_version_id=ANY(%s)
                ORDER BY v.content_type,v.channel,v.version_number FOR SHARE OF v""",
                (workspace_id, task_id, manifest_ids),
            )
            versions = [{**row, "content_version_id": str(row["content_version_id"])} for row in await package_cursor.fetchall()]
            if len(versions) != len(manifest_ids):
                raise ToolRejected("Final package manifest references unavailable versions")
            current_channels_cursor = await connection.execute(
                """SELECT DISTINCT ON (channel) channel,content_version_id
                FROM content_versions
                WHERE workspace_id=%s AND task_id=%s AND channel IS NOT NULL
                ORDER BY channel,version_number DESC,created_at DESC""",
                (workspace_id, task_id),
            )
            current_channels = {
                row["channel"]: str(row["content_version_id"])
                for row in await current_channels_cursor.fetchall()
            }
            manifest_channels = {
                item["channel"]: item["content_version_id"]
                for item in versions if item["channel"]
            }
            if current_channels != manifest_channels:
                raise ToolRejected("Channel versions changed after final approval")
            digest_payload = [
                {"content_version_id": item["content_version_id"], "content_type": item["content_type"],
                 "channel": item["channel"], "immutable_hash": item["immutable_hash"]}
                for item in versions
            ]
            gate_cursor = await connection.execute(
                """SELECT t.selected_channels,
                  (SELECT COUNT(*) FROM review_issues i WHERE i.workspace_id=t.workspace_id AND i.task_id=t.task_id AND i.severity='critical' AND i.status='open') AS critical_count,
                  (SELECT COUNT(*) FROM content_lineage l WHERE l.workspace_id=t.workspace_id AND l.task_id=t.task_id AND l.status='unsupported_new_claim') AS unsupported_count,
                  (SELECT g.version FROM content_briefs b JOIN brand_guideline_versions g ON g.workspace_id=b.workspace_id AND g.brand_id=b.brand_id AND g.active=TRUE WHERE b.workspace_id=t.workspace_id AND b.task_id=t.task_id ORDER BY g.created_at DESC LIMIT 1) AS brand_guideline_version
                FROM content_tasks t WHERE t.workspace_id=%s AND t.task_id=%s FOR SHARE OF t""",
                (workspace_id, task_id),
            )
            gate = await gate_cursor.fetchone()
            channel_versions = [item for item in digest_payload if item["channel"]]
            master_versions = [item for item in digest_payload if not item["channel"]]
            if not gate or gate["critical_count"] or gate["unsupported_count"] or len(master_versions) != 1:
                raise ToolRejected("Final package no longer satisfies critical issue, factual lineage, or canonical master gates")
            required_channels = sorted(gate["selected_channels"])
            if sorted(item["channel"] for item in channel_versions) != required_channels:
                raise ToolRejected("Required channel set changed after final approval")
            spec_cursor = await connection.execute(
                "SELECT channel,version FROM channel_spec_versions WHERE workspace_id=%s AND channel=ANY(%s) AND active=TRUE ORDER BY channel",
                (workspace_id, required_channels),
            )
            spec_versions = {row["channel"]: row["version"] for row in await spec_cursor.fetchall()}
            fact_cursor = await connection.execute(
                """SELECT f.fact_id,f.version FROM content_briefs b JOIN verified_facts f
                  ON f.workspace_id=b.workspace_id AND f.product_id=b.product_id
                WHERE b.workspace_id=%s AND b.task_id=%s AND f.status='active' AND f.public_usage_allowed=TRUE
                  AND (f.effective_at IS NULL OR f.effective_at<=NOW()) AND (f.expires_at IS NULL OR f.expires_at>NOW())
                ORDER BY f.fact_id""",
                (workspace_id, task_id),
            )
            fact_versions = [{"fact_id": str(row["fact_id"]), "version": row["version"]} for row in await fact_cursor.fetchall()]
            snapshot = {"versions": digest_payload, "required_channels": required_channels, "channel_spec_versions": spec_versions, "brand_guideline_version": gate["brand_guideline_version"], "authoritative_fact_versions": fact_versions}
            if snapshot != manifest["snapshot"]:
                raise ToolRejected("Final gate evidence changed after approval")
            actual_hash = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if actual_hash != target_snapshot_hash:
                raise ToolRejected("Approved package snapshot no longer matches the authorized target")
            await connection.execute(
                """INSERT INTO idempotency_records
                (workspace_id,actor_id,action,immutable_target,idempotency_key,request_hash,status,expires_at)
                VALUES(%s,%s,%s,%s,%s,%s,'started',NOW()+INTERVAL '24 hours')""",
                (workspace_id, actor_id, action, actual_hash, idempotency_key, request_hash),
            )
            package = {"task_id": task_id, "versions": versions}
            try:
                artifacts = render_package(package, formats)
            except ValueError as error:
                raise ToolRejected(str(error)) from error
            result = {"package": package, "formats": sorted(set(formats)), "artifacts": artifacts, "package_hash": actual_hash}
            await connection.execute(
                """UPDATE idempotency_records SET status='succeeded',response_status=200,response_body=%s,updated_at=NOW()
                WHERE workspace_id=%s AND actor_id=%s AND action=%s AND idempotency_key=%s""",
                (json.dumps(result), workspace_id, actor_id, action, idempotency_key),
            )
            return result, False
