from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_api.domain.models import AgentState, DecisionOutcome, ReviewSummary
from agent_api.providers.base import LLMProvider


class ContextGateway(Protocol):
    async def retrieve(self, state: AgentState) -> dict[str, object]: ...


class VersionRepository(Protocol):
    async def save(
        self,
        *,
        state: AgentState,
        content_type: str,
        content: str,
        parent_version_id: str | None = None,
    ) -> str: ...

    async def get_content(self, *, state: AgentState, version_id: str) -> str: ...


class DecisionGateway(Protocol):
    async def resolve(self, *, decision_id: str, state: AgentState, scope: str, version_id: str | None) -> DecisionOutcome: ...


class MasterReviewGateway(Protocol):
    async def review(self, *, state: AgentState, content: str) -> list[ReviewSummary]: ...


class DeterministicMasterReviewer:
    async def review(self, *, state: AgentState, content: str) -> list[ReviewSummary]:
        content_text = content.casefold()
        required_messages = state.brief.required_messages if state.brief else []
        forbidden_claims = state.brief.forbidden_claims if state.brief else []
        missing_messages = [message for message in required_messages if message.casefold() not in content_text]
        found_forbidden = [claim for claim in forbidden_claims if claim.casefold() in content_text]

        def summary(review_type: str, passed: bool, issues: list[str]) -> ReviewSummary:
            return ReviewSummary(
                review_type=review_type,
                passed=passed,
                critical_issues=issues,
                revision_instructions=[f"Resolve {issue}" for issue in issues],
            )

        return [
            summary("factual", bool(state.verified_fact_ids and content.strip()), ["No verified factual basis"] if not state.verified_fact_ids else []),
            summary("citation", bool(state.retrieved_source_ids and content.strip()), ["Source coverage is missing"] if not state.retrieved_source_ids else []),
            summary("brief_coverage", not missing_messages, [f"Missing required message: {message}" for message in missing_messages]),
            summary("brand", bool(state.brand_guideline_version), ["Active brand guideline is missing"] if not state.brand_guideline_version else []),
            summary("compliance", not found_forbidden, [f"Forbidden claim present: {claim}" for claim in found_forbidden]),
        ]


class WorkflowRuntime(Protocol):
    async def is_cancelled(self, state: AgentState) -> bool: ...
    async def persist_transition(self, state: AgentState, updates: dict[str, object], event_type: str) -> None: ...
    async def persist_reviews(self, state: AgentState, reviews: list[ReviewSummary]) -> None: ...


@dataclass(frozen=True, slots=True)
class WorkflowDependencies:
    provider: LLMProvider
    context: ContextGateway
    versions: VersionRepository
    decisions: DecisionGateway
    runtime: WorkflowRuntime | None = None
    reviewer: MasterReviewGateway | None = None
