from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent_api.domain.errors import NotFoundError


class PostgresKnowledgeRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._pool: AsyncConnectionPool | None = None

    async def open(self) -> None:
        self._pool = AsyncConnectionPool(self._database_url, open=False, kwargs={"row_factory": dict_row})
        await self._pool.open()

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def _scope(self, connection, workspace_id: str) -> None:
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))

    async def product_facts(self, workspace_id: str) -> list[dict[str, Any]]:
        async with self._pool.connection() as connection:  # type: ignore[union-attr]
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT fact_id, fact_content, product_id, source_document_id,
                          version, authority_level, effective_at, expires_at
                FROM verified_facts
                WHERE workspace_id = %s AND status = 'active' AND public_usage_allowed = TRUE
                  AND (effective_at IS NULL OR effective_at <= NOW())
                  AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY CASE authority_level WHEN 'primary' THEN 1 WHEN 'approved' THEN 2 ELSE 3 END,
                         effective_at DESC NULLS LAST
                LIMIT 200""",
                (workspace_id,),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "id": str(row["fact_id"]),
                    "title": row["fact_content"][:120] if row.get("fact_content") else "",
                    "content": row.get("fact_content", ""),
                    "product_id": row.get("product_id", ""),
                    "source": f"source_doc:{row['source_document_id']}" if row.get("source_document_id") else "",
                    "authority": row.get("authority_level", ""),
                    "version": row.get("version", 1),
                    "effective_at": str(row["effective_at"]) if row.get("effective_at") else None,
                }
                for row in rows
            ]

    async def brand_guidelines(self, workspace_id: str) -> list[dict[str, Any]]:
        async with self._pool.connection() as connection:  # type: ignore[union-attr]
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT guideline_version_id, brand_id, version, positioning,
                          standard_terms, tone, required_language, forbidden_expressions,
                          cta_guidance, effective_at
                FROM brand_guideline_versions
                WHERE workspace_id = %s AND active = TRUE
                  AND (effective_at IS NULL OR effective_at <= NOW())
                  AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY created_at DESC
                LIMIT 50""",
                (workspace_id,),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "id": str(row["guideline_version_id"]),
                    "title": f"品牌规范 v{row.get('version', 1)}",
                    "brand_id": row.get("brand_id", ""),
                    "version": row.get("version", 1),
                    "positioning": row.get("positioning", ""),
                    "tone": row.get("tone", ""),
                    "standard_terms": row.get("standard_terms", ""),
                    "required_language": row.get("required_language", ""),
                    "forbidden_expressions": row.get("forbidden_expressions", ""),
                    "source": f"brand:{row.get('brand_id', '')}",
                }
                for row in rows
            ]

    async def channel_guidelines(self, workspace_id: str) -> list[dict[str, Any]]:
        async with self._pool.connection() as connection:  # type: ignore[union-attr]
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT channel_spec_version_id, channel, version,
                          length_rules, required_fields, tone, cta_style,
                          hashtag_rules, forbidden_patterns
                FROM channel_spec_versions
                WHERE workspace_id = %s AND active = TRUE
                ORDER BY channel, created_at DESC
                LIMIT 50""",
                (workspace_id,),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "id": str(row["channel_spec_version_id"]),
                    "title": f"{row.get('channel', '')} 渠道规范",
                    "channel": row.get("channel", ""),
                    "version": row.get("version", 1),
                    "length_rules": row.get("length_rules", ""),
                    "required_fields": row.get("required_fields", ""),
                    "tone": row.get("tone", ""),
                    "source": f"channel_spec:{row.get('channel', '')}",
                }
                for row in rows
            ]

    async def approved_content(self, workspace_id: str) -> list[dict[str, Any]]:
        async with self._pool.connection() as connection:  # type: ignore[union-attr]
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT cv.content_version_id, cv.task_id, cv.content_type,
                          cv.channel, cv.version_number, cv.content,
                          cv.immutable_hash, cv.created_at,
                          ct.title AS task_title
                FROM content_versions cv
                JOIN content_tasks ct ON ct.workspace_id = cv.workspace_id AND ct.task_id = cv.task_id
                WHERE cv.workspace_id = %s
                  AND cv.content_type = 'master'
                  AND EXISTS (
                    SELECT 1 FROM human_decisions hd
                    WHERE hd.workspace_id = cv.workspace_id
                      AND hd.task_id = cv.task_id
                      AND hd.decision IN ('approve', 'authorize')
                      AND hd.target_snapshot_hash = cv.immutable_hash
                  )
                ORDER BY cv.created_at DESC
                LIMIT 100""",
                (workspace_id,),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "id": str(row["content_version_id"]),
                    "title": row.get("task_title", "") or f"内容版本 v{row.get('version_number', 1)}",
                    "task_id": str(row["task_id"]) if row.get("task_id") else "",
                    "version": row.get("version_number", 1),
                    "content": (row.get("content", "") or "")[:500],
                    "channel": row.get("channel", ""),
                    "source": f"task:{row.get('task_id', '')}",
                    "created_at": str(row["created_at"]) if row.get("created_at") else None,
                }
                for row in rows
            ]

    async def forbidden_claims(self, workspace_id: str) -> list[dict[str, Any]]:
        async with self._pool.connection() as connection:  # type: ignore[union-attr]
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT guideline_version_id, brand_id, version,
                          forbidden_expressions, effective_at
                FROM brand_guideline_versions
                WHERE workspace_id = %s AND active = TRUE
                  AND forbidden_expressions IS NOT NULL
                  AND forbidden_expressions != ''
                  AND (effective_at IS NULL OR effective_at <= NOW())
                  AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY created_at DESC
                LIMIT 50""",
                (workspace_id,),
            )
            rows = await cursor.fetchall()
            items: list[dict[str, Any]] = []
            for row in rows:
                expressions = (row.get("forbidden_expressions") or "").strip()
                if not expressions:
                    continue
                for expr in expressions.split("\n"):
                    expr = expr.strip()
                    if expr:
                        items.append({
                            "id": f"{row['guideline_version_id']}:{hash(expr) & 0x7FFFFFFF:x}",
                            "title": expr[:120],
                            "expression": expr,
                            "brand_id": row.get("brand_id", ""),
                            "source": f"brand:{row.get('brand_id', '')}",
                        })
            return items[:200]
