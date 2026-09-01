"""Citation validation for the research experiment.

Two-level check per evidence card:
1. URL reachable (HEAD, allow redirects, no body parse — we do NOT
   fetch-and-parse untrusted pages for the experiment; reachability is
   the gate, excerpt fidelity comes from Tavily's own chunk content).
2. Excerpt fidelity: the quoted span must be a (whitespace-normalized)
   verbatim substring of the content Tavily returned for that URL.

The plan's injection rule stands: fetched bytes are only ever compared,
never fed to a model prompt.
"""

from __future__ import annotations

import asyncio
import re

import httpx

_UA = "BrandAgent-Research-Validator/1.0 (+experiment; reachability check)"
_CONCURRENCY = 6


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


async def check_card(card, *, client: httpx.AsyncClient) -> dict:
    """Return {url, ok, excerpts_ok: [bool per excerpt]}."""
    result = {"url": card.url, "ok": False, "excerpts_ok": []}
    try:
        response = await client.head(card.url, follow_redirects=True, timeout=12)
        result["ok"] = response.status_code < 400
    except Exception:  # noqa: BLE001 — unreachability is a finding, not a crash
        result["ok"] = False
    # excerpt fidelity against the provider content we recorded at retrieval
    source = _norm(getattr(card, "_source_content", "") or "")
    for excerpt in card.excerpts:
        if not source:
            result["excerpts_ok"].append(False)
            continue
        result["excerpts_ok"].append(_norm(excerpt) in source)
    return result


async def validate_evidence(cards) -> list[dict]:
    if not cards:
        return []
    async with httpx.AsyncClient(
        headers={"User-Agent": _UA}, follow_redirects=True, timeout=12
    ) as client:
        semaphore = asyncio.Semaphore(_CONCURRENCY)

        async def guarded(card):
            async with semaphore:
                return await check_card(card, client=client)

        return await asyncio.gather(*(guarded(c) for c in cards))
