"""Citation validation for the deep-research PRODUCT path.

Tavily is the sole web-fetch egress for deep research.  Its result already
contains the source URL and retrieved content; probing that URL a second time
from BrandAgent creates an unnecessary SSRF surface and is vulnerable to DNS
rebinding between a policy lookup and the actual connection.  This gate is
therefore deliberately local:

- source URL: allow only a safe public ``http(s)`` URL for the UI link;
- excerpt fidelity: compare against Tavily's retrieved content;
- no application-owned request, DNS resolution, redirect following, or HTML
  processing.

The experiment validator remains separate so historical experiment data is
unchanged.  Fetched content is only compared, never placed in a system prompt.
"""

from __future__ import annotations

import re

from agent_api.domain.consumer import assert_safe_material_url

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


async def check_card(card) -> dict:
    """Return {url, ok, excerpts_ok: [bool per excerpt]} — verdict shapes
    stay compatible with the experiment validator.
    """
    result = {"url": card.url, "ok": False, "excerpts_ok": []}
    try:
        assert_safe_material_url(card.url)
        result["ok"] = True
    except Exception:  # noqa: BLE001 — unsafe or malformed source is a finding
        result["ok"] = False
    source = _norm(getattr(card, "_source_content", "") or "")
    for excerpt in card.excerpts:
        if not source:
            result["excerpts_ok"].append(False)
            continue
        result["excerpts_ok"].append(_norm(excerpt) in source)
    return result


async def validate_evidence_safely(cards) -> list[dict]:
    """Product citation gate: safe URL shape + excerpt fidelity, no egress."""
    if not cards:
        return []
    return [await check_card(card) for card in cards]
