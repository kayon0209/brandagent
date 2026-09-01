"""Research-evaluation metrics (Phase 6 controlled experiment).

Single source of truth for the experiment's scoring rules. Both the
runner and the report import from here, so S0/S1/S2 can never be graded
by different logic (experiment-integrity rule).

All metrics are computed from STRUCTURED evidence fields only — never by
parsing generated prose — matching the consumer golden-gate convention.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class EvidenceCard:
    """One retrieved+validated source unit produced by any strategy."""

    url: str
    title: str
    excerpts: list[str]  # quoted spans claimed to come from the source
    score: float | None = None
    retrieved_at: str = ""

    def key(self) -> str:
        return hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:16]


@dataclass
class StrategyRun:
    """One (strategy, question, seed) execution and everything we bill it by."""

    strategy: str  # S0 | S1 | S2
    question_id: str
    difficulty: str
    seed: int
    answer: str
    evidence: list[EvidenceCard] = field(default_factory=list)
    model_calls: int = 0
    search_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    canceled: bool = False
    partial: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def cost_credits(self) -> float:
        # search credits: 1 per basic search (Tavily contract); model cost
        # is tracked in tokens, converted by the report, not here
        return float(self.search_calls)


def valid_citation_rate(run: StrategyRun, checks: list[dict]) -> float:
    """Fraction of cited claims whose URL is reachable AND every excerpt
    is a verbatim substring of the fetched content (checks come from the
    citation validator; each entry {url, excerpts_ok: list[bool]})."""
    if not checks:
        return 0.0
    total = sum(len(c["excerpts_ok"]) for c in checks)
    if total == 0:
        return 0.0
    good = sum(1 for c in checks for ok in c["excerpts_ok"] if ok)
    return good / total


def coverage(run: StrategyRun) -> int:
    """Number of DISTINCT sources (by URL hash) the strategy cited."""
    return len({e.key() for e in run.evidence})


def duplication_rate(run: StrategyRun) -> float:
    """Redundant evidence fraction (same source cited by multiple cards)."""
    keys = [e.key() for e in run.evidence]
    if not keys:
        return 0.0
    return 1 - len(set(keys)) / len(keys)


def contradiction_reported(run: StrategyRun) -> bool:
    """Did the answer surface conflicting evidence instead of hiding it?

    Structural proxy (no prose parsing): >=2 distinct sources AND the
    answer contains an explicit conflict marker from the fixed lexicon
    the strategies are all instructed to use when evidence disagrees.
    """
    if coverage(run) < 2:
        return False
    markers = ("冲突", "矛盾", "不一致", "存在分歧", "相反", "争议")
    return any(m in run.answer for m in markers)


def unsupported_claim_rate(run: StrategyRun, answer_claims: list[dict]) -> float:
    """Fraction of factual claims in the answer with NO supporting
    evidence card (claims are extracted structurally by the runner: each
    {claim, evidence_keys: [...]}; a claim is unsupported when none of
    its evidence keys exist in the run's evidence)."""
    if not answer_claims:
        return 0.0
    have = {e.key() for e in run.evidence}
    unsupported = sum(
        1 for c in answer_claims if not (set(c["evidence_keys"]) & have)
    )
    return unsupported / len(answer_claims)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
