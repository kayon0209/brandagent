"""Consumer draft generation graph (real construction, not mocks).

The production container 500'd on POST /draft/generate with
`TypeError: unhashable type: 'dict'`: langgraph >= 1.2.10 rejects bare
dict state schemas. These tests build and INVOKE the real graph so a
schema or version regression fails here, not in front of a user.
"""

from __future__ import annotations

import pytest

from agent_api.providers.base import ModelCallResult, ProviderExecutionError
from agent_api.workflow.consumer_graph import (
    GeneratedDraft,
    GraphCandidateGenerator,
    build_consumer_graph,
)


def _result(text: str) -> ModelCallResult:
    return ModelCallResult(
        content=text,
        provider="stub",
        model="stub",
        prompt_version="consumer-draft-gen:v1",
        latency_ms=5,
        input_tokens=10,
        output_tokens=10,
        usage_source="none",
        retry_count=0,
    )


class StubProvider:
    def __init__(self, text: str) -> None:
        self.text = text

    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        return _result(self.text)


class UnknownExecutionProvider:
    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        raise ProviderExecutionError(
            "MODEL_EXECUTION_UNKNOWN",
            "The provider may have executed the request but its response was lost.",
            retryable=False,
        )


class ConfirmedExecutionProvider:
    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        raise ProviderExecutionError(
            "MODEL_INVALID_RESPONSE",
            "The provider returned a malformed success response.",
            retryable=False,
            execution_confirmed=True,
        )


CANDIDATE_TEXT = "品牌不是自动化出来的，而是一个人持续做判断的结果。工具替你完成句子，观点的代价仍在你身上。"


@pytest.mark.asyncio
async def test_build_consumer_graph_compiles_with_typed_state() -> None:
    """langgraph must accept the state schema — the bare-dict schema this
    replaced raised `unhashable type: 'dict'` at construction (500).
    build_consumer_graph returns the compiled graph directly."""

    graph = build_consumer_graph(
        provider=StubProvider(CANDIDATE_TEXT),
        core_idea="品牌靠判断",
        intent="自由写作",
        excerpts=[],
        base_revision=1,
    )
    assert graph is not None
    assert set(graph.get_graph().nodes) >= {
        "collect_linked_excerpts",
        "generate_draft",
        "review_draft",
        "persist_candidate",
    }


@pytest.mark.asyncio
async def test_full_graph_invoke_produces_candidate_and_usage() -> None:
    generator = GraphCandidateGenerator(provider=StubProvider(CANDIDATE_TEXT))
    usage: dict = {}
    candidate = await generator.generate(
        core_idea="品牌靠判断",
        intent="",
        excerpts=[{"excerpt_text": "判断是品牌的核心"}],
        base_revision=3,
        usage_out=usage,
    )
    assert candidate["plain_text"].strip()
    assert candidate["prompt_version"] == "consumer-draft-gen:v1"
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 10
    assert usage["model"] == "stub"


@pytest.mark.asyncio
async def test_short_output_is_rejected_by_the_deterministic_review() -> None:
    generator = GraphCandidateGenerator(provider=StubProvider("太短"))
    usage: dict = {}
    with pytest.raises(RuntimeError, match="CANDIDATE_REJECTED"):
        await generator.generate(
            core_idea="品牌靠判断",
            intent="",
            excerpts=[],
            base_revision=1,
            usage_out=usage,
        )
    assert usage == {
        "input_tokens": 10,
        "output_tokens": 10,
        "model": "stub",
        "model_executed": True,
    }


@pytest.mark.asyncio
async def test_response_loss_preserves_the_execution_unknown_semantic_for_usage() -> None:
    generator = GraphCandidateGenerator(provider=UnknownExecutionProvider())
    with pytest.raises(ProviderExecutionError) as caught:
        await generator.generate(
            core_idea="品牌靠判断",
            intent="",
            excerpts=[],
            base_revision=1,
        )
    assert caught.value.code == "MODEL_EXECUTION_UNKNOWN"
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_confirmed_provider_execution_is_not_downgraded_by_the_graph() -> None:
    generator = GraphCandidateGenerator(provider=ConfirmedExecutionProvider())
    with pytest.raises(ProviderExecutionError) as caught:
        await generator.generate(
            core_idea="品牌靠判断",
            intent="",
            excerpts=[],
            base_revision=1,
        )
    assert caught.value.code == "MODEL_INVALID_RESPONSE"
    assert caught.value.execution_confirmed is True


def test_generated_draft_accepts_only_substantive_text() -> None:
    substantive = "品牌不是自动化出来的，而是一个人持续做判断的结果，这句足够长。"
    assert GeneratedDraft([{"text": substantive}], substantive).accepted
    assert not GeneratedDraft([{"text": "太短"}], "太短").accepted
