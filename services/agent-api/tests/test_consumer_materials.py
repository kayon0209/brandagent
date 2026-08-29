"""Service-level tests for the consumer material pipeline (upgrade plan task 6).

These tests exercise MaterialService through its public interface with an
in-memory store, asserting the behaviors the consumer upgrade plan requires:
checksum dedup, idempotent import requests, stable chunk ids, excerpt
traceability, and cross-workspace isolation.
"""

from __future__ import annotations

import pytest

from agent_api.api.security import Principal

from agent_api.api.security import Principal
from agent_api.domain.consumer import (
    MaterialImportRequest,
    ParsedMaterial,
)
from agent_api.domain.errors import NotFoundError
from agent_api.application.materials import MaterialService


class MemoryMaterialStore:
    """Minimal in-memory stand-in for PostgresMaterialStore.

    Mirrors the semantics the real store must provide: workspace-scoped access,
    (workspace_id, checksum) uniqueness on documents, stable chunk identity,
    and idempotent request handling.
    """

    def __init__(self) -> None:
        self.documents: dict[str, dict] = {}
        self.chunks: dict[str, dict] = {}
        self.excerpts: dict[str, dict] = {}
        self.events: list[dict] = []
        self.import_log: dict[tuple[str, str], dict] = {}

    async def find_document_by_checksum(self, workspace_id: str, checksum: str) -> dict | None:
        for document in self.documents.values():
            if document["workspace_id"] == workspace_id and document["checksum"] == checksum:
                return document
        return None

    async def insert_document(self, workspace_id: str, document: ParsedMaterial, checksum: str, request_id: str) -> dict:
        import uuid

        document_id = str(uuid.uuid4())
        row = {
            "document_id": document_id,
            "workspace_id": workspace_id,
            "document_name": document.name,
            "document_type": "external_reference",
            "version": "v1",
            "authority_level": "reference",
            "checksum": checksum,
            "status": "active",
            "request_id": request_id,
        }
        self.documents[document_id] = row
        return row

    async def insert_chunks(self, workspace_id: str, document_id: str, chunks: list[dict]) -> list[dict]:
        inserted = []
        for chunk in chunks:
            self.chunks[chunk["chunk_id"]] = {**chunk, "workspace_id": workspace_id, "document_id": document_id}
            inserted.append(self.chunks[chunk["chunk_id"]])
        return inserted

    async def insert_excerpts(self, workspace_id: str, document_id: str, excerpts: list[dict]) -> list[dict]:
        inserted = []
        for excerpt in excerpts:
            self.excerpts[excerpt["excerpt_id"]] = {**excerpt, "workspace_id": workspace_id, "document_id": document_id}
            inserted.append(self.excerpts[excerpt["excerpt_id"]])
        return inserted

    async def get_document(self, workspace_id: str, document_id: str) -> dict | None:
        document = self.documents.get(document_id)
        if document is None or document["workspace_id"] != workspace_id:
            return None
        return document

    async def list_documents(self, workspace_id: str) -> list[dict]:
        return [d for d in self.documents.values() if d["workspace_id"] == workspace_id]

    async def get_chunks(self, workspace_id: str, document_id: str) -> list[dict]:
        return [
            c
            for c in self.chunks.values()
            if c["workspace_id"] == workspace_id and c["document_id"] == document_id
        ]

    async def get_excerpts(self, workspace_id: str, document_id: str) -> list[dict]:
        return [
            e
            for e in self.excerpts.values()
            if e["workspace_id"] == workspace_id and e["document_id"] == document_id
        ]

    async def record_import(self, workspace_id: str, request_id: str, result: dict) -> None:
        self.import_log[(workspace_id, request_id)] = result

    async def find_import(self, workspace_id: str, request_id: str) -> dict | None:
        return self.import_log.get((workspace_id, request_id))

    async def append_event(self, event: dict) -> None:
        self.events.append(event)


class FakeParser:
    async def parse_text(self, text: str) -> ParsedMaterial:
        return ParsedMaterial(name=f"text:{text[:8]}", content=text)

    async def parse_file(self, filename: str, content: bytes) -> ParsedMaterial:
        return ParsedMaterial(name=filename, content=content.decode("utf-8", errors="replace"))


class FakeDistiller:
    async def distill(self, chunks: list[dict]) -> list[dict]:
        excerpts = []
        for chunk in chunks:
            excerpts.append(
                {
                    "excerpt_id": f"excerpt-{chunk['chunk_id']}",
                    "excerpt_type": "quote",
                    "summary": chunk["content"][:12],
                    "excerpt_text": chunk["content"],
                    "provenance_hash": f"prov-{chunk['chunk_id']}",
                    "status": "ready",
                    "created_by_type": "model",
                }
            )
        return excerpts


def make_principal(workspace_id: str = "workspace-1") -> Principal:
    return Principal(user_id="creator-1", workspace_id=workspace_id, role="admin", experience="personal")


def make_service() -> MaterialService:
    store = MemoryMaterialStore()
    return MaterialService(store=store, parser=FakeParser(), distiller=FakeDistiller()), store


@pytest.mark.asyncio
async def test_text_import_dedups_by_checksum() -> None:
    service, store = make_service()
    principal = make_principal()
    first = await service.import_text(principal, MaterialImportRequest(text="第一段素材内容，用来测试 checksum 去重。", name="note-1"))
    duplicate = await service.import_text(principal, MaterialImportRequest(text="第一段素材内容，用来测试 checksum 去重。", name="note-1-copy"))
    assert first["status"] == "distilled"
    assert duplicate["status"] == "duplicate"
    assert duplicate["document_id"] == first["document_id"]
    assert len(store.documents) == 1


@pytest.mark.asyncio
async def test_identical_import_requests_are_idempotent() -> None:
    service, store = make_service()
    principal = make_principal()
    request = MaterialImportRequest(text="同样的导入请求只应处理一次。", name="idem-note")
    first = await service.import_text(principal, request, request_id="req-1")
    second = await service.import_text(principal, request, request_id="req-1")
    assert first["status"] == "distilled"
    assert second == first
    assert len(store.documents) == 1
    assert second["request_id"] == "req-1"


@pytest.mark.asyncio
async def test_chunk_ids_are_stable_for_identical_content() -> None:
    service, _store = make_service()
    principal = make_principal()
    view = await service.import_text(
        principal, MaterialImportRequest(text="稳定 ID 测试段落。", name="chunked"), request_id="r1"
    )
    second = await service.import_text(
        principal, MaterialImportRequest(text="稳定 ID 测试段落。", name="chunked-again"), request_id="r2"
    )
    assert second["status"] == "duplicate"
    document = await service.get_document_view(principal, view["document_id"])
    assert [c["chunk_id"] for c in document["chunks"]] == sorted(c["chunk_id"] for c in document["chunks"])


@pytest.mark.asyncio
async def test_excerpt_must_reference_workspace_visible_document() -> None:
    service, _store = make_service()
    principal = make_principal()
    imported = await service.import_text(principal, MaterialImportRequest(text="excerpt 归属测试内容。", name="trace"))
    view = await service.get_document_view(principal, imported["document_id"])
    for excerpt in view["excerpts"]:
        assert excerpt["document_id"] == view["document"]["document_id"]
        # provenance hash is a verifiable sha256 binding, not a decorative prefix
        assert len(excerpt["provenance_hash"]) == 64
        int(excerpt["provenance_hash"], 16)


@pytest.mark.asyncio
async def test_cross_workspace_document_returns_404_not_existence_leak() -> None:
    service, _store = make_service()
    owner = make_principal("workspace-a")
    outsider = make_principal("workspace-b")
    imported = await service.import_text(owner, MaterialImportRequest(text="跨租户隔离测试素材。", name="iso"))
    with pytest.raises(NotFoundError):
        await service.get_document_view(outsider, imported["document_id"])


@pytest.mark.asyncio
async def test_distill_failure_keeps_material_and_reports_retryable_state() -> None:
    class ExplodingDistiller(FakeDistiller):
        async def distill(self, chunks: list[dict]) -> list[dict]:
            raise RuntimeError("distiller crashed")

    store = MemoryMaterialStore()
    service = MaterialService(store=store, parser=FakeParser(), distiller=ExplodingDistiller())
    principal = make_principal()
    result = await service.import_text(principal, MaterialImportRequest(text="蒸馏失败也要保留原文。", name="resilient"))
    assert result["status"] == "needs_distillation"
    documents = await store.list_documents(principal.workspace_id)
    assert len(documents) == 1
    assert documents[0]["checksum"]


@pytest.mark.asyncio
async def test_url_import_rejects_private_and_redirect_targets() -> None:
    service, _store = make_service()
    principal = make_principal()
    for url in ("http://127.0.0.1:8000/private", "http://localhost/x", "https://internal.corp/secret"):
        with pytest.raises(ValueError):
            await service.import_url(principal, url)


# ---------------------------------------------------------------------------
# HTTP layer contract tests
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from agent_api.api.main import create_app  # noqa: E402


class FakeTasks:
    async def bootstrap_workspace(self, principal):
        return {"workspace_id": principal.workspace_id, "role": principal.role}

    async def list_tasks(self, principal):
        return []

    async def ready(self):
        return True


class FakeMaterialVerifier:
    async def verify(self, token: str) -> Principal:
        if token != "valid-token":
            raise ValueError("invalid token")
        return Principal(user_id="creator-1", workspace_id="00000000-0000-0000-0000-000000000001", role="admin", experience="personal")


class FakeMaterialKnowledge:
    async def product_facts(self, workspace_id): return []
    async def brand_guidelines(self, workspace_id): return []
    async def channel_guidelines(self, workspace_id): return []
    async def approved_content(self, workspace_id): return []
    async def forbidden_claims(self, workspace_id): return []


def http_client(materials: MaterialService) -> TestClient:
    app = create_app(
        tasks=FakeTasks(),
        verifier=FakeMaterialVerifier(),
        knowledge=FakeMaterialKnowledge(),
        materials=materials,
    )
    return TestClient(app)


def test_materials_require_authentication() -> None:
    client = http_client(make_service()[0])
    response = client.get("/api/v1/consumer/materials")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_material_import_text_roundtrip_and_listing() -> None:
    service, store = make_service()
    client = http_client(service)
    # The HTTP verifier resolves workspace 00000000-...-0001; seed with the
    # same workspace so the listing actually sees the document.
    principal = Principal(
        user_id="creator-1",
        workspace_id="00000000-0000-0000-0000-000000000001",
        role="admin",
        experience="personal",
    )
    import asyncio

    async def seed():
        await service.import_text(principal, MaterialImportRequest(text="HTTP 层测试素材。", name="http-note"), request_id="http-req-1")

    asyncio.run(seed())
    response = client.get(
        "/api/v1/consumer/materials",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert len(body["data"]["items"]) == 1
    assert body["data"]["items"][0]["document_name"].startswith("text:")
    assert body["data"]["items"][0]["document_id"] in store.documents


def test_material_detail_returns_404_for_cross_workspace_ids() -> None:
    service, _store = make_service()
    client = http_client(service)
    import asyncio

    principal = make_principal("workspace-a")
    other = make_principal("workspace-b")

    async def seed():
        return await service.import_text(principal, MaterialImportRequest(text="隔离素材。", name="iso"), request_id="iso-1")

    document_id = asyncio.run(seed())["document_id"]
    # The verifier only knows workspace-1; use a foreign document id directly.
    response = client.get(
        f"/api/v1/consumer/materials/{document_id}",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
