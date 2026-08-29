"""Consumer material application service (upgrade plan task 6).

Coordinates parsing, chunking, distillation, storage, and public events.
Ports (store, parser, distiller) are injected; the service itself never
touches SQL or HTTP directly.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from agent_api.api.security import Principal
from agent_api.domain.consumer import (
    MaterialImportRequest,
    MaterialValidationError,
    ParsedMaterial,
    UploadLimits,
    assert_safe_material_url,
    chunk_id,
    chunk_material,
    material_checksum,
    provenance_hash,
    validate_upload,
)
from agent_api.domain.errors import NotFoundError


class MaterialStore(Protocol):
    """Persistence port for consumer materials."""

    async def find_document_by_checksum(self, workspace_id: str, checksum: str) -> dict | None: ...
    async def insert_document(self, workspace_id: str, material: ParsedMaterial, checksum: str, request_id: str) -> dict: ...
    async def insert_chunks(self, workspace_id: str, document_id: str, chunks: list[dict]) -> list[dict]: ...
    async def insert_excerpts(self, workspace_id: str, document_id: str, excerpts: list[dict]) -> list[dict]: ...
    async def get_document(self, workspace_id: str, document_id: str) -> dict | None: ...
    async def get_chunks(self, workspace_id: str, document_id: str) -> list[dict]: ...
    async def get_excerpts(self, workspace_id: str, document_id: str) -> list[dict]: ...
    async def list_documents(self, workspace_id: str) -> list[dict]: ...
    async def record_import(self, workspace_id: str, request_id: str, result: dict) -> None: ...
    async def find_import(self, workspace_id: str, request_id: str) -> dict | None: ...
    async def append_event(self, event: dict) -> None: ...


class MaterialParser(Protocol):
    """Parsing port (task 6 Step 3: text and md/txt first)."""

    async def parse_text(self, text: str) -> ParsedMaterial: ...
    async def parse_file(self, filename: str, content: bytes) -> ParsedMaterial: ...


class MaterialDistiller(Protocol):
    """Distillation port: chunks in, structured excerpts out."""

    async def distill(self, chunks: list[dict]) -> list[dict]: ...


_EVENT_IMPORTED = "consumer.material.imported.v1"
_EVENT_PARSING = "consumer.material.parsing.v1"
_EVENT_DISTILLED = "consumer.material.distilled.v1"
_EVENT_FAILED = "consumer.material.failed.v1"


class MaterialService:
    def __init__(
        self,
        *,
        store: MaterialStore,
        parser: MaterialParser,
        distiller: MaterialDistiller,
        limits: UploadLimits | None = None,
    ) -> None:
        self._store = store
        self._parser = parser
        self._distiller = distiller
        self._limits = limits or UploadLimits()

    # ------------------------------------------------------------------
    # Events (public payload never includes raw text)
    # ------------------------------------------------------------------

    async def _emit(self, workspace_id: str, request_id: str, event_type: str, payload: dict) -> None:
        await self._store.append_event(
            {
                "workspace_id": workspace_id,
                "request_id": request_id,
                "type": event_type,
                # Only ids, status, progress, and safe error codes — no raw text.
                "data": payload,
            }
        )

    # ------------------------------------------------------------------
    # Import pipeline
    # ------------------------------------------------------------------

    async def _import_parsed(
        self,
        principal: Principal,
        material: ParsedMaterial,
        *,
        request_id: str,
        source_kind: str,
    ) -> dict:
        workspace_id = principal.workspace_id
        existing_import = await self._store.find_import(workspace_id, request_id)
        if existing_import is not None:
            return existing_import

        checksum = material_checksum(material.content)
        await self._emit(workspace_id, request_id, _EVENT_IMPORTED, {"source_kind": source_kind, "status": "accepted"})

        duplicate = await self._store.find_document_by_checksum(workspace_id, checksum)
        if duplicate is not None:
            result = {
                "status": "duplicate",
                "document_id": duplicate["document_id"],
                "checksum": checksum,
                "request_id": request_id,
            }
            await self._store.record_import(workspace_id, request_id, result)
            return result

        await self._emit(workspace_id, request_id, _EVENT_PARSING, {"status": "parsing"})
        document = await self._store.insert_document(workspace_id, material, checksum, request_id)

        chunks_payload = [
            {"chunk_id": chunk_id(checksum, index, text), "chunk_index": index, "content": text}
            for index, text in enumerate(chunk_material(material.content))
        ]
        if not chunks_payload:
            return await self._record_status(
                workspace_id, document, checksum, request_id, status="needs_distillation"
            )
        chunks = await self._store.insert_chunks(workspace_id, document["document_id"], chunks_payload)

        try:
            distilled = await self._distiller.distill(chunks)
        except Exception:  # noqa: BLE001 — any distiller failure must be survivable
            await self._emit(
                workspace_id, request_id, _EVENT_FAILED,
                {"document_id": document["document_id"], "error_code": "DISTILL_FAILED", "retryable": True},
            )
            return await self._record_status(
                workspace_id, document, checksum, request_id, status="needs_distillation"
            )

        accepted: list[dict] = []
        for excerpt in distilled:
            chunk = next((c for c in chunks if c["chunk_id"] == excerpt.get("chunk_id")), None)
            if chunk is None:
                # excerpt must quote verbatim from a real chunk of this document
                matching = [c for c in chunks if isinstance(excerpt.get("excerpt_text"), str) and excerpt["excerpt_text"] in c["content"]]
                if not matching:
                    continue
                chunk = matching[0]
            excerpt_row = {
                "excerpt_id": excerpt.get("excerpt_id") or str(uuid4()),
                "chunk_id": chunk["chunk_id"],
                "excerpt_type": excerpt.get("excerpt_type", "quote"),
                "summary": excerpt.get("summary", ""),
                "excerpt_text": excerpt["excerpt_text"],
                "tags": excerpt.get("tags", []),
                "provenance_hash": provenance_hash(checksum, chunk["chunk_id"], excerpt["excerpt_text"]),
                "status": excerpt.get("status", "ready"),
                "created_by_type": excerpt.get("created_by_type", "model"),
            }
            accepted.append(excerpt_row)

        if not accepted:
            await self._emit(
                workspace_id, request_id, _EVENT_FAILED,
                {"document_id": document["document_id"], "error_code": "DISTILL_NO_EVIDENCE", "retryable": True},
            )
            return await self._record_status(
                workspace_id, document, checksum, request_id, status="needs_review"
            )

        stored = await self._store.insert_excerpts(workspace_id, document["document_id"], accepted)
        await self._emit(
            workspace_id, request_id, _EVENT_DISTILLED,
            {"document_id": document["document_id"], "status": "distilled", "excerpt_count": len(stored)},
        )
        result = {
            "status": "distilled",
            "document_id": document["document_id"],
            "checksum": checksum,
            "request_id": request_id,
        }
        await self._store.record_import(workspace_id, request_id, result)
        return result

    async def _record_status(
        self, workspace_id: str, document: dict, checksum: str, request_id: str, *, status: str
    ) -> dict:
        result = {
            "status": status,
            "document_id": document["document_id"],
            "checksum": checksum,
            "request_id": request_id,
        }
        await self._store.record_import(workspace_id, request_id, result)
        return result

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------

    async def import_text(self, principal: Principal, request: MaterialImportRequest, request_id: str | None = None) -> dict:
        material = await self._parser.parse_text(request.text)
        return await self._import_parsed(
            principal, material, request_id=request_id or str(uuid4()), source_kind="text"
        )

    async def import_url(self, principal: Principal, url: str, request_id: str | None = None) -> dict:
        assert_safe_material_url(url)
        # URL fetching itself is a later task concern; the contract test only
        # requires the SSRF gate to raise before any fetch happens.
        raise NotImplementedError("URL fetching arrives with the fetch adapter")

    async def upload_file(
        self, principal: Principal, filename: str, payload: bytes, *, content_type: str = "", request_id: str | None = None
    ) -> dict:
        extension = validate_upload(filename, payload, content_type, self._limits)
        material = await self._parser.parse_file(filename, payload)
        return await self._import_parsed(
            principal, material, request_id=request_id or str(uuid4()), source_kind=f"upload:{extension}"
        )

    async def get_document_view(self, principal: Principal, document_id: str) -> dict:
        document = await self._store.get_document(principal.workspace_id, document_id)
        if document is None:
            # Cross-workspace ids resolve to a plain 404: no existence leak.
            raise NotFoundError("Material not found")
        chunks = await self._store.get_chunks(principal.workspace_id, document_id)
        excerpts = await self._store.get_excerpts(principal.workspace_id, document_id)
        return {"document": document, "chunks": chunks, "excerpts": excerpts}

    async def list_documents(self, principal: Principal) -> list[dict]:
        return await self._store.list_documents(principal.workspace_id)


# ---------------------------------------------------------------------------
# MVP default implementations (task 6 Step 3: text, md, txt first)
# ---------------------------------------------------------------------------

class SimpleTextParser:
    """Parses plain text and md/txt uploads into a ParsedMaterial."""

    async def parse_text(self, text: str) -> ParsedMaterial:
        return ParsedMaterial(name=f"note-{uuid4().hex[:8]}", content=text)

    async def parse_file(self, filename: str, content: bytes) -> ParsedMaterial:
        return ParsedMaterial(name=filename, content=content.decode("utf-8", errors="replace"))


class HeuristicDistiller:
    """Deterministic MVP distiller: each chunk becomes a verbatim quote excerpt.

    No model calls: the excerpt text is exactly the chunk content, which
    keeps provenance containment trivially true and predictable.
    """

    max_summary_chars = 48

    async def distill(self, chunks: list[dict]) -> list[dict]:
        excerpts = []
        for chunk in chunks:
            content = chunk["content"]
            summary = content.strip().replace("\n", " ")
            if len(summary) > self.max_summary_chars:
                summary = summary[: self.max_summary_chars - 1] + "…"
            excerpts.append(
                {
                    "excerpt_id": str(uuid5(NAMESPACE_URL, f"brandagent:excerpt:v1:{chunk['chunk_id']}")),
                    "chunk_id": chunk["chunk_id"],
                    "excerpt_type": "quote",
                    "summary": summary,
                    "excerpt_text": content,
                    "tags": [],
                    "status": "ready",
                    "created_by_type": "model",
                }
            )
        return excerpts
