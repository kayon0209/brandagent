"""Search-provider adapter (Phase 6 experiment).

Contract for the ONE outbound web channel the experiment is allowed to
use. Design rules from the plan:

- Tavily is the only fetch egress; we NEVER fetch raw URLs ourselves
  (no SSRF surface, no untrusted HTML into prompts).
- Response is normalized into EvidenceCard seeds; `content` strings are
  DATA — callers must put them into user-visible evidence fields, never
  into system instructions (prompt-injection rule).
- Timeboxed + retried; failures are reported, not swallowed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

import httpx


class BudgetExceeded(RuntimeError):
    """Raised BEFORE any further provider call when the run's search
    budget cap is reached; strategies MUST let it propagate."""


class SearchProvider(Protocol):
    async def search(self, query: str, *, max_results: int = 5) -> list[dict]:
        """Return [{url, title, content, score}] — normalized search hits."""


@dataclass
class TavilySearchProvider:
    api_key: str
    base_url: str = "https://api.tavily.com"
    timeout_seconds: float = 20.0
    max_retries: int = 2
    # billing counter: incremented on EVERY outbound HTTP attempt so the
    # experiment's search_calls always equals real provider requests
    call_counter: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.call_counter is None:
            self.call_counter = [0]

    async def search(self, query: str, *, max_results: int = 5) -> list[dict]:
        last_error: Exception | None = None
        for attempt in range(1 + self.max_retries):
            try:
                self.call_counter[0] += 1
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(
                        f"{self.base_url}/search",
                        json={
                            "api_key": self.api_key,
                            "query": query,
                            "search_depth": "basic",
                            "max_results": max_results,
                            "include_answer": False,
                        },
                    )
                    if response.status_code == 429:
                        raise RuntimeError("TAVILY_RATE_LIMIT")
                    response.raise_for_status()
                    payload = response.json()
                return [
                    {
                        "url": hit.get("url", ""),
                        "title": hit.get("title", ""),
                        "content": hit.get("content", ""),
                        "score": hit.get("score"),
                    }
                    for hit in payload.get("results", [])
                    if hit.get("url")
                ]
            except Exception as error:  # noqa: BLE001 — surfaced, not hidden
                last_error = error
                if attempt < self.max_retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"tavily search failed after retries: {last_error}")


@dataclass
class RecordedSearchProvider:
    """Test double: scripted results, records every query (no network)."""

    script: list[dict]  # returned verbatim (already normalized)
    queries: list[str] = None  # type: ignore[assignment]
    call_counter: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.queries = []
        if self.call_counter is None:
            self.call_counter = [0]

    async def search(self, query: str, *, max_results: int = 5) -> list[dict]:
        self.queries.append(query)
        if self.call_counter is not None:
            self.call_counter[0] += 1
        return self.script

    call_counter: list = None
