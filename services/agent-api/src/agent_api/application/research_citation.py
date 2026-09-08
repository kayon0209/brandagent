"""SSRF-hardened citation validation for the deep-research PRODUCT path.

The experiment's citation.py (research/ package) follows redirects with
NO host validation — acceptable for a curated eval dataset, unacceptable
for the product: a hostile search result could make the server HEAD
internal addresses (169.254.169.254 cloud metadata, localhost services,
RFC1918 ranges). The experiment file stays untouched (experiment-integrity
rule); this is the product seam with the same VERDICT semantics:

- reachability: HEAD, 3-hop manual redirect loop, EVERY hop re-validated
  (literal host check + full DNS resolution) BEFORE any network I/O;
- excerpt fidelity: whitespace-normalized verbatim substring of the
  content the provider returned for that URL (unchanged rule);
- no redirect auto-follow: each hop's Location is resolved and re-gated
  the same way the material import does (v4 P0-1 discipline).

Fetched bytes are only ever compared, never fed to a model prompt
(plan §10 injection rule).
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpx

from agent_api.domain.consumer import assert_safe_material_url

_UA = "BrandAgent-Research-Validator/1.1 (+product; SSRF-gated reachability)"
_CONCURRENCY = 4
_TIMEOUT = 12.0
_MAX_REDIRECTS = 3


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _assert_safe_resolved_url(url: str) -> str:
    """Literal-host check + full DNS resolution, private ranges rejected.

    Same two-layer rule as the material import (v4 P0-1): the literal
    check kills odd IP spellings and non-http(s) schemes; the resolution
    step kills 'public domain that answers on a private IP'.
    """
    safe_url = assert_safe_material_url(url)
    parsed = urlsplit(safe_url)
    host = parsed.hostname or ""
    infos = socket.getaddrinfo(
        host,
        parsed.port or (443 if parsed.scheme == "https" else 80),
        proto=socket.IPPROTO_TCP,
    )
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
            raise ValueError(f"blocked target: {host}")


async def check_card(card, *, client: httpx.AsyncClient) -> dict:
    """Return {url, ok, excerpts_ok: [bool per excerpt]} — verdict shapes
    identical to the experiment validator so metrics stay comparable."""
    result = {"url": card.url, "ok": False, "excerpts_ok": []}
    current = card.url
    try:
        # manual redirect loop: every hop is validated BEFORE the request,
        # never auto-followed (a 302 to an internal address must not fire).
        for _hop in range(_MAX_REDIRECTS + 1):
            _assert_safe_resolved_url(current)
            response = await client.head(current, follow_redirects=False, timeout=_TIMEOUT)
            if 300 <= response.status_code < 400:
                location = response.headers.get("location")
                if not location:
                    break
                current = urljoin(current, location)
                continue
            result["ok"] = response.status_code < 400
            break
    except Exception:  # noqa: BLE001 — unreachability is a finding, not a crash
        result["ok"] = False
    source = _norm(getattr(card, "_source_content", "") or "")
    for excerpt in card.excerpts:
        if not source:
            result["excerpts_ok"].append(False)
            continue
        result["excerpts_ok"].append(_norm(excerpt) in source)
    return result


async def validate_evidence_safely(cards) -> list[dict]:
    """Product citation gate: SSRF-safe reachability + excerpt fidelity."""
    if not cards:
        return []
    async with httpx.AsyncClient(
        headers={"User-Agent": _UA},
        follow_redirects=False,  # the loop in check_card owns redirects
        timeout=_TIMEOUT,
        trust_env=False,
    ) as client:
        semaphore = asyncio.Semaphore(_CONCURRENCY)

        async def guarded(card):
            async with semaphore:
                return await check_card(card, client=client)

        return await asyncio.gather(*(guarded(c) for c in cards))
