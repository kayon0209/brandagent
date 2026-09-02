"""Free-intent propose (agentization P1: bounded intent panel).

propose_from_intent is ONE classifier call in front of the existing
anchored propose path. These tests pin: classification into each of the
three actions reuses propose() exactly (anchor, guardrails, suggestion
row); out-of-palette intents are refused structurally (never guessed);
format drift (intent: expand。) is tolerated; empty/oversize intents
fail validation; propose-level refusals surface as content_guard.
"""

from __future__ import annotations

import pytest

from agent_api.api.security import Principal
from agent_api.application.editorial_assist import (
    ActionNotSupported,
    EditorialAssistService,
    SelectionStale,
)
from agent_api.providers.base import ModelCallResult
from tests.test_editorial_assist import (  # noqa: F401 — reused fixtures
    BASE_TEXT,
    TARGET,
    MemorySuggestionStore,
    make_service,
    principal_for,
)


class SequencedProvider:
    """Returns verdict-then-rewrite from a scripted list of contents."""

    def __init__(self, contents: list[str]) -> None:
        self.contents = list(contents)
        self.calls: list[str] = []

    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        self.calls.append(prompt_version)
        content = self.contents.pop(0) if self.contents else ""
        return ModelCallResult(
            content=content,
            provider="stub",
            model="stub",
            prompt_version=prompt_version,
            latency_ms=5,
            input_tokens=5,
            output_tokens=5,
            usage_source="none",
            retry_count=0,
        )


def _anchor_kwargs() -> dict:
    return {
        "selected_text": TARGET,
        "block_id": "b1",
        "base_revision": 3,
        "start_offset": 6,
        "end_offset": 6 + len(TARGET) - 1,
    }


@pytest.mark.asyncio
async def test_intent_classified_as_expand_reuses_anchored_propose() -> None:
    provider = SequencedProvider(["expand", "更充实的改写句子。"])
    service, store = make_service(provider)
    result = await service.propose_from_intent(
        principal_for("ws-1"), "task-1", intent="把这句话写得更有细节", **_anchor_kwargs()
    )
    assert result["status"] == "proposed"
    assert result["suggestion"]["action"] == "expand"
    assert provider.calls == ["editorial-assist:intent:v1", "editorial-assist:expand:v1"]
    assert store.suggestions  # suggestion row persisted through the real path


@pytest.mark.asyncio
async def test_intent_format_drift_is_tolerated() -> None:
    provider = SequencedProvider(["intent: shorten。", "精简句。"])
    service, _ = make_service(provider)
    result = await service.propose_from_intent(
        principal_for("ws-1"), "task-1", intent="短一点", **_anchor_kwargs()
    )
    assert result["status"] == "proposed"
    assert result["suggestion"]["action"] == "shorten"


@pytest.mark.asyncio
async def test_out_of_palette_intent_is_refused_structurally() -> None:
    provider = SequencedProvider(["refuse"])
    service, _ = make_service(provider)
    result = await service.propose_from_intent(
        principal_for("ws-1"), "task-1", intent="把这句话翻译成英文", **_anchor_kwargs()
    )
    assert result["status"] == "refused"
    assert result["reason"] == "unsupported_intent"
    assert result["supported_actions"] == ["expand", "replace_example", "shorten"]
    assert len(provider.calls) == 1  # no second (rewrite) call after refusal


@pytest.mark.asyncio
async def test_gibberish_verdict_is_refused_not_guessed() -> None:
    provider = SequencedProvider(["我觉得可以试试重新组织"])
    service, _ = make_service(provider)
    result = await service.propose_from_intent(
        principal_for("ws-1"), "task-1", intent="随便说点什么", **_anchor_kwargs()
    )
    assert result["status"] == "refused"
    assert result["reason"] == "unsupported_intent"
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_propose_level_refusal_surfaces_as_content_guard() -> None:
    # classifier says expand, but the rewrite contains an unsupported
    # numeric claim -> propose() returns None -> content_guard refusal
    provider = SequencedProvider(["expand", "销量增长了300%。"])
    service, _ = make_service(provider)
    result = await service.propose_from_intent(
        principal_for("ws-1"), "task-1", intent="写得更具体", **_anchor_kwargs()
    )
    assert result["status"] == "refused"
    assert result["reason"] == "content_guard"


@pytest.mark.asyncio
async def test_stale_selection_still_raises_conflict_through_intent_path() -> None:
    provider = SequencedProvider(["shorten", "短句。"])
    service, _ = make_service(provider)
    stale = _anchor_kwargs() | {"start_offset": 0, "end_offset": 2}
    with pytest.raises(SelectionStale):
        await service.propose_from_intent(principal_for("ws-1"), "task-1", intent="精简", **stale)


@pytest.mark.asyncio
async def test_empty_and_oversize_intents_are_validation_errors() -> None:
    provider = SequencedProvider([])
    service, _ = make_service(provider)
    with pytest.raises(ValueError):
        await service.propose_from_intent(principal_for("ws-1"), "task-1", intent="   ", **_anchor_kwargs())
    with pytest.raises(ValueError):
        await service.propose_from_intent(
            principal_for("ws-1"), "task-1", intent="长" * 201, **_anchor_kwargs()
        )
    assert provider.calls == []  # no model call spent on invalid input


@pytest.mark.asyncio
async def test_usage_of_both_calls_is_reported() -> None:
    provider = SequencedProvider(["expand", "充实版本。"])
    service, _ = make_service(provider)
    usage: dict = {}
    result = await service.propose_from_intent(
        principal_for("ws-1"), "task-1", intent="展开说说", usage_out=usage, **_anchor_kwargs()
    )
    assert result["status"] == "proposed"
    # usage_out carries the rewrite call (settle), result carries classifier
    assert usage.get("output_tokens") == 5
    assert result["usage"]["output_tokens"] == 5
