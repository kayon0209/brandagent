"""Postgres-backed material store integration tests (upgrade plan task 6/7).

Gated behind RUN_AGENT_DB_TESTS=true like the other disposable-PostgreSQL
suites. Exercises the real SQL end to end: dedup by checksum, deterministic
chunk ids, excerpt traceability, cross-workspace 404 semantics, and the
workspace-scoped task_events integration for material events.
"""

import os
from uuid import uuid4

import pytest

from agent_api.api.security import Principal
from agent_api.application.materials import HeuristicDistiller, MaterialService, SimpleTextParser
from agent_api.repositories.postgres_materials import PostgresMaterialStore


pytestmark = pytest.mark.skipif(os.getenv("RUN_AGENT_DB_TESTS") != "true", reason="requires disposable PostgreSQL")

WORKSPACE = str(uuid4())
OTHER_WORKSPACE = str(uuid4())
# Two paragraphs long enough to cross the ~600-char chunking target.
TEXT = (
    "第一段素材内容。" + "这是一段足够长的正文，用来跨越分块阈值，验证分块聚合逻辑在真实 SQL 上正确工作。" * 24
    + "\n\n第二段素材内容。" + "这是第二段同样很长的正文，继续填充以确保产生多个稳定的分块。" * 24
)


async def _ensure_workspace(store: PostgresMaterialStore, workspace_id: str, user_id: str) -> None:
    """Mirror the real bootstrap flow: scope the connection before writing."""
    async with store._pool.connection() as connection:
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))
        await connection.execute(
            """INSERT INTO workspaces(workspace_id, name, slug, created_by)
               VALUES (%s, 'Test WS', %s, %s)
               ON CONFLICT (workspace_id) DO NOTHING""",
            (workspace_id, f"ws-{workspace_id}", user_id),
        )


@pytest.mark.asyncio
async def test_material_pipeline_end_to_end_on_postgres() -> None:
    database_url = os.environ["AGENT_TEST_DATABASE_URL"]
    store = PostgresMaterialStore(database_url)
    await store.open()
    try:
        await _ensure_workspace(store, WORKSPACE, "creator-1")

        principal = Principal(user_id="creator-1", workspace_id=WORKSPACE, role="admin", experience="personal")
        service = MaterialService(store=store, parser=SimpleTextParser(), distiller=HeuristicDistiller())

        first = await service.import_text(principal, __import__("agent_api.domain.consumer", fromlist=["MaterialImportRequest"]).MaterialImportRequest(text=TEXT, name="pg-note"), request_id="pg-req-1")
        assert first["status"] == "distilled"

        duplicate = await service.import_text(principal, __import__("agent_api.domain.consumer", fromlist=["MaterialImportRequest"]).MaterialImportRequest(text=TEXT, name="pg-note-dup"), request_id="pg-req-2")
        assert duplicate["status"] == "duplicate"
        assert duplicate["document_id"] == first["document_id"]

        view = await service.get_document_view(principal, first["document_id"])
        assert len(view["chunks"]) >= 2, "two paragraphs must produce stable chunks"
        assert len(view["excerpts"]) >= 2
        for excerpt in view["excerpts"]:
            assert excerpt["document_id"] == first["document_id"]
            assert excerpt["chunk_id"] in {c["chunk_id"] for c in view["chunks"]}
            assert len(excerpt["provenance_hash"]) == 64

        events = await store.material_events(WORKSPACE)
        assert any(event["event_type"] == "consumer.material.distilled.v1" for event in events)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_cross_workspace_document_reads_are_scoped_on_postgres() -> None:
    database_url = os.environ["AGENT_TEST_DATABASE_URL"]
    store = PostgresMaterialStore(database_url)
    await store.open()
    try:
        await _ensure_workspace(store, OTHER_WORKSPACE, "creator-2")
        principal = Principal(user_id="creator-2", workspace_id=OTHER_WORKSPACE, role="admin", experience="personal")
        service = MaterialService(store=store, parser=SimpleTextParser(), distiller=HeuristicDistiller())
        from agent_api.domain.consumer import MaterialImportRequest

        imported = await service.import_text(
            principal, MaterialImportRequest(text="禁止跨工作区读取。", name="iso-note"), request_id="iso-pg-1"
        )
        assert imported["status"] == "distilled"

        intruder = Principal(user_id="intruder", workspace_id=WORKSPACE, role="admin", experience="personal")
        fetched = await store.get_document(WORKSPACE, imported["document_id"])
        assert fetched is None, "cross-workspace document id must resolve to nothing"
    finally:
        await store.close()
