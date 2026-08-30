"""Consumer material domain contracts (upgrade plan task 6).

Pure domain rules: import request shapes, upload limits, chunking, checksum,
provenance hash, URL safety, and upload payload validation. No I/O here.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import struct
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field


class ConsumerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Import requests
# ---------------------------------------------------------------------------

class MaterialImportRequest(ConsumerModel):
    """Paste-text import body."""

    text: str = Field(min_length=1, max_length=200_000)
    name: str = Field(default="", max_length=200)


@dataclass(frozen=True, slots=True)
class ParsedMaterial:
    """Parser output: a named body of text ready for chunking."""

    name: str
    content: str


@dataclass(frozen=True, slots=True)
class UploadLimits:
    """Default hard limits for material uploads (task 6 Step 1)."""

    max_bytes: int = 10 * 1024 * 1024
    allowed_extensions: frozenset[str] = frozenset({"md", "txt"})
    max_pages: int = 100
    max_url_chars: int = 100_000


class MaterialValidationError(ValueError):
    """Raised when an upload or import violates the material contract."""


# ---------------------------------------------------------------------------
# Checksum, chunking, provenance
# ---------------------------------------------------------------------------

def material_checksum(workspace_id: str, content: str) -> str:
    """Stable content checksum used for workspace-level dedup.

    The workspace seeds the digest (security-review P2 fix): identical text
    imported in two workspaces derives independent checksums/chunk ids and
    can never collide on the global primary keys.
    """
    return hashlib.sha256(f"material:v1:{workspace_id}:{content}".encode("utf-8")).hexdigest()


def chunk_material(content: str, *, target_chars: int = 600) -> list[str]:
    """Split text into paragraph-boundary chunks of roughly target_chars.

    Chunk ids are stable because both the content and the split are
    deterministic: identical content always produces identical chunks.
    """
    if not content.strip():
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    chunks: list[str] = []
    buffer: list[str] = []
    size = 0
    for paragraph in paragraphs:
        if buffer and size + len(paragraph) > target_chars:
            chunks.append("\n\n".join(buffer))
            buffer, size = [], 0
        buffer.append(paragraph)
        size += len(paragraph)
    if buffer:
        chunks.append("\n\n".join(buffer))
    return chunks


def chunk_id(document_checksum: str, chunk_index: int, chunk_text: str) -> str:
    """Deterministic chunk identity: a stable UUID bound to content and index.

    Being a UUID keeps the id directly compatible with the source_chunks
    primary key while remaining reproducible across identical imports.
    """
    return str(uuid5(NAMESPACE_URL, f"brandagent:chunk:v1:{document_checksum}:{chunk_index}:{chunk_text}"))


def provenance_hash(document_checksum: str, chunk_id: str, excerpt_text: str) -> str:
    """Binds an excerpt to its document, chunk, and verbatim text."""
    return hashlib.sha256(f"provenance:v1:{document_checksum}:{chunk_id}:{excerpt_text}".encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# URL safety (SSRF)
# ---------------------------------------------------------------------------

_PRIVATE_HOSTS = frozenset(
    {
        "localhost",
        "0.0.0.0",
        "metadata.google.internal",
    }
)

_PRIVATE_PREFIXES = (
    "127.",
    "10.",
    "172.16.",
    "172.17.",
    "172.18.",
    "172.19.",
    "172.20.",
    "172.21.",
    "172.22.",
    "172.23.",
    "172.24.",
    "172.25.",
    "172.26.",
    "172.27.",
    "172.28.",
    "172.29.",
    "172.30.",
    "172.31.",
    "192.168.",
    "169.254.",
    "192.0.0.",
    "198.18.",
    "198.19.",
)


def assert_safe_material_url(url: str) -> str:
    """Validate a user-submitted URL for material import; raise on private targets.

    Returns the canonical http(s) URL. DNS-based private resolution happens at
    fetch time; this gate rejects literal private hosts, ALL numeric IPv4
    spellings (dotted, integer, hex, octal — inet_aton normalizes them),
    non-http(s) schemes, and missing hosts outright.
    """
    try:
        parts = urlsplit(url)
    except ValueError as error:
        raise MaterialValidationError("URL is not valid") from error
    if parts.scheme not in ("http", "https"):
        raise MaterialValidationError("Only http(s) URLs can be imported")
    host = (parts.hostname or "").lower()
    if not host:
        raise MaterialValidationError("URL host is required")
    if (
        host in _PRIVATE_HOSTS
        or any(host.startswith(hint) for hint in _PRIVATE_PREFIXES)
        or host.endswith(".local")
        or host.endswith(".internal")
        or host.endswith(".corp")
        or host.endswith(".lan")
    ):
        raise MaterialValidationError("Private network URLs cannot be imported")
    # numeric forms: inet_aton accepts "2130706433", "0x7f000001", "0177.0.0.1"
    try:
        packed = socket.inet_aton(host)
        (numeric_ipv4,) = struct.unpack("!I", packed)
        host_for_ip = str(ipaddress.ip_address(numeric_ipv4))
    except (OSError, struct.error):
        host_for_ip = host
    try:
        address = ipaddress.ip_address(host_for_ip)
    except ValueError:
        pass
    else:
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_unspecified:
            raise MaterialValidationError("Private network URLs cannot be imported")
    if host.startswith("[") or ":" in host:
        # IPv6 literal already handled above; defensive double-check for zone indexes.
        raise MaterialValidationError("Private network URLs cannot be imported")
    return url


# ---------------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------------

_MIME_BY_EXTENSION = {
    "md": "text/markdown",
    "txt": "text/plain",
}

_PDF_MIME = "application/pdf"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def validate_upload(filename: str, payload: bytes, content_type: str, limits: UploadLimits) -> str:
    """Validate an uploaded material file; return its normalized extension.

    Rejection order is security-first: size, spoofed MIME (executable bytes
    declared as a document), encrypted PDFs, macro documents, then the
    extension allowlist and declared-MIME consistency for allowed types.
    """
    if len(payload) > limits.max_bytes:
        raise MaterialValidationError(f"File exceeds the {limits.max_bytes} byte size limit")

    lowered_name = filename.lower()
    extension = lowered_name.rsplit(".", 1)[-1] if "." in lowered_name else ""
    declared = (content_type or "").split(";")[0].strip().lower()

    # 1. Executable magic bytes are never legitimate material, whatever the declared type.
    if payload.startswith(b"MZ") or payload.startswith(b"\x7fELF"):
        raise MaterialValidationError(f"Spoofed MIME type: executable payload declared as {declared or 'unknown'}")

    # 2. PDF family: declared PDFs must actually be PDFs, and never encrypted.
    if declared == _PDF_MIME or extension == "pdf":
        if not payload.lower().startswith(b"%pdf"):
            raise MaterialValidationError("Spoofed MIME type: payload is not a PDF document")
        if b"/encrypt" in payload.lower()[:65536]:
            raise MaterialValidationError("encrypted PDFs are not supported")

    # 3. DOCX family: declared DOCX must be a zip package, and never macro-enabled.
    if declared == _DOCX_MIME or extension == "docx":
        if not payload.startswith(b"PK\x03\x04"):
            raise MaterialValidationError("Spoofed MIME type: payload is not a DOCX document")
        if b"vbaproject" in payload.lower()[:65536]:
            raise MaterialValidationError("macro-enabled documents are not supported")

    # 4. Extension allowlist: task 6 MVP accepts text and markdown only.
    if extension not in limits.allowed_extensions:
        raise MaterialValidationError(f"Unsupported file type: .{extension or 'unknown'}")

    expected_mime = _MIME_BY_EXTENSION[extension]
    if declared and declared not in (expected_mime, "application/octet-stream"):
        raise MaterialValidationError(f"Spoofed MIME type: .{extension} must be {expected_mime}, got {declared}")
    return extension
