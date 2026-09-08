"""Consumer material application service (upgrade plan task 6).

Coordinates parsing, chunking, distillation, storage, and public events.
Ports (store, parser, distiller) are injected; the service itself never
touches SQL or HTTP directly.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

from agent_api.api.security import Principal
import httpx

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

# v4 P0-2: hard cap on the body we pull from a user-supplied link. The BFF's
# 12 MB ceiling only bounds the *upload*; the server-side fetch had none, so
# a giant "page" could exhaust the agent-api process. 2 MB is generous for
# readable text and keeps memory bounded.
_MAX_FETCH_BYTES = 2 * 1024 * 1024
# v4 P0-1: we never auto-follow redirects (a 302 to 169.254.169.254 / 127.0.0.1
# would otherwise bypass the first-hop check). Manual loop, 3 hops max.
_MAX_REDIRECTS = 3
_OVERSIZE_MSG = "该页面内容过大（超过 2 MB），无法保存为文字素材。可改用「粘贴文字」导入正文。"


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

        # checksum is workspace-seeded: identical text in two workspaces can
        # never collide on global chunk/excerpt primary keys (review P2)
        checksum = material_checksum(workspace_id, material.content)
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
        material = ParsedMaterial(
            # the PARSER owns the display name (existing behavior, pinned by
            # tests: FakeParser yields "text:…"); request.name stays advisory
            # and never overrides it
            name=material.name,
            content=material.content,
            document_type="text",
        )
        return await self._import_parsed(
            principal, material, request_id=request_id or str(uuid4()), source_kind="text"
        )

    async def import_research_card(
        self,
        principal: Principal,
        *,
        name: str,
        content: str,
        source_url: str,
        request_id: str,
    ) -> dict:
        """Phase 6 加入素材: a deep-research candidate card becomes a
        traceable link-kind material. Reuses the whole import pipeline
        (checksum dedup, deterministic chunks, provenance, events) — the
        recorded excerpt text is the body, so nothing depends on the live
        page still being reachable."""
        material = ParsedMaterial(
            name=name,
            content=content,
            document_type="link",
            source_url=source_url,
        )
        return await self._import_parsed(
            principal, material, request_id=request_id, source_kind=f"research-card:{source_url}"
        )

    async def import_url(self, principal: Principal, url: str, request_id: str | None = None) -> dict:
        """round-3g D6: save-a-link import — fetch the page, strip markup,
        store the readable text with the URL as provenance. Failures are
        honest errors; a fetch that returns no usable text never imports a
        fake article body.

        SSRF hardening (v4 P0-1 / P0-2): we never auto-follow redirects, and
        every hop — including redirect targets — is re-validated by host AND
        by resolving every A/AAAA record (rejecting private/loopback/
        link-local/reserved ranges). The response body is streamed with a
        hard 2 MB cap.
        """
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            # Validate this hop BEFORE any network I/O. Raises ValueError for
            # literal private hosts or DNS records resolving to private space.
            self._assert_safe_resolved_url(current)
            status, content_type, body, location = await self._fetch_link_text(current)
            if 300 <= status < 400:
                if not location:
                    raise ValueError("链接返回了重定向，但没有目标地址，已停止抓取。")
                current = urljoin(current, location)
                continue
            if status >= 400:
                raise ValueError(f"链接返回 HTTP {status}，没有拿到内容。可改用「粘贴文字」导入正文。")
            break
        else:
            raise ValueError("链接重定向次数过多，已停止抓取。")

        if content_type and content_type not in ("text/html", "text/plain", "application/xhtml+xml"):
            raise ValueError(f"该链接是 {content_type}，不是网页正文，无法保存为文字素材。")

        title, body_text = self._extract_readable_html(body)
        if not body_text:
            raise ValueError("该页面没有提取到可读正文（可能是脚本渲染页）。请改用「粘贴文字」导入正文。")

        material = ParsedMaterial(
            name=title or url,
            content=body_text,
            document_type="link",
            source_url=url,
        )
        return await self._import_parsed(
            principal, material, request_id=request_id or str(uuid4()), source_kind=f"link:{url}"
        )

    def _assert_safe_resolved_url(self, url: str) -> None:
        """Reject unsafe link targets (v4 P0-1).

        Two layers, both required:
          1. ``assert_safe_material_url`` rejects literal private hosts,
             non-http(s) schemes, and numeric/encoded IP spellings.
          2. We then resolve every A/AAAA record and reject if ANY candidate
             is private / loopback / link-local / reserved / unspecified /
             multicast — closing the "domain points at 127.0.0.1" bypass that
             the old first-hop-only check allowed.

        Residual risk (documented in v4 SUMMARY): a DNS-rebinding attack
        between this ``getaddrinfo`` call and httpx's own connect could still
        swap in a private IP. Closing it fully needs an IP-pinning transport,
        which the MVP fetch path intentionally does not add.
        """
        safe_url = assert_safe_material_url(url)  # raises on literal private / bad scheme
        parsed = urlsplit(safe_url)
        host = parsed.hostname or ""
        try:
            infos = socket.getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                proto=socket.IPPROTO_TCP,
            )
        except socket.gaierror as error:
            raise ValueError(f"无法解析链接域名（{error}），请检查链接是否正确。") from error
        for _family, _type, _proto, _canon, sockaddr in infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_unspecified
                or ip.is_multicast
            ):
                raise ValueError("该链接指向的地址不允许导入")

    async def _fetch_link_text(self, url: str) -> tuple[int, str, str, str | None]:
        """Stream a link target's body with a 2 MB cap.

        Returns ``(status, content_type, decoded_text, location_header)``.
        Redirects are NOT followed here — the caller loops and re-validates
        each hop. A body larger than ``_MAX_FETCH_BYTES`` raises an honest
        error without loading it fully into memory.
        """
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=15.0,
                trust_env=False,
                headers={"User-Agent": "BrandAgent-Material/1.0"},
            ) as client:
                async with client.stream("GET", url) as response:
                    status = response.status_code
                    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
                    location = response.headers.get("location")
                    length = response.headers.get("content-length")
                    if length and int(length) > _MAX_FETCH_BYTES:
                        raise ValueError(_OVERSIZE_MSG)
                    body = b""
                    async for chunk in response.aiter_bytes(8192):
                        body += chunk
                        if len(body) > _MAX_FETCH_BYTES:
                            raise ValueError(_OVERSIZE_MSG)
                    encoding = response.encoding or "utf-8"
        except httpx.HTTPError as error:
            raise ValueError(
                f"链接抓取失败（{type(error).__name__}），请检查链接是否可访问，或改用「粘贴文字」导入。"
            ) from error
        text = body.decode(encoding, errors="replace")
        return status, content_type, text, location

    @staticmethod
    def _extract_readable_html(html: str) -> tuple[str | None, str]:
        """Best-effort title + visible-text extraction. No JS execution and
        no claims of readability — if the text layer is empty we say so."""
        import html as _html
        import re as _re

        title_match = _re.search(r"<title[^>]*>(.*?)</title>", html, _re.IGNORECASE | _re.DOTALL)
        title = (_re.sub(r"<[^>]+>", "", title_match.group(1)).strip()[:80]) if title_match else None
        cleaned = _re.sub(r"<(script|style|noscript|nav|header|footer)[^>]*>.*?</\1>", " ", html, flags=_re.IGNORECASE | _re.DOTALL)
        cleaned = _re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", cleaned, flags=_re.IGNORECASE)
        cleaned = _re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = _html.unescape(cleaned)
        lines = [line.strip() for line in cleaned.splitlines()]
        body = "\n".join(line for line in lines if line)
        return title, body

    async def upload_file(
        self, principal: Principal, filename: str, payload: bytes, *, content_type: str = "", request_id: str | None = None
    ) -> dict:
        extension = validate_upload(filename, payload, content_type, self._limits)
        material = await self._parser.parse_file(filename, payload)
        material = ParsedMaterial(
            name=material.name,
            content=material.content,
            document_type="file",
            original_filename=filename,
        )
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
        # round-3g D6 honesty rule: a PDF's text layer cannot be read from
        # raw bytes; utf-8 replace would import garbage as if it were
        # content. Reject with the spoken reason instead.
        if filename.lower().endswith(".pdf") or content.lower().startswith(b"%pdf"):
            raise ValueError("该 PDF 无法提取文本（当前版本仅支持 txt / md 文本文件）。请改用「粘贴文字」。")
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
