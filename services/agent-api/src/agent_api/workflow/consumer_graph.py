"""Consumer draft generation workflow (upgrade plan task 8).

A compact LangGraph graph that orchestrates candidate generation for the
consumer manuscript. Unlike the enterprise master-content graph there are
NO approval interrupts here: collect linked excerpts -> call the model ->
deterministic review -> persist a candidate version. User drafts are never
overwritten by the graph; applying a candidate is a separate, explicit
compare-and-swap performed by DraftGenerationService.

Prompts live in this module (application layer), never in the API route.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from agent_api.providers.base import LLMProvider, ProviderExecutionError


PROMPT_VERSION = "consumer-draft-gen:v1"

SYSTEM_PROMPT = (
    "你是一位帮助个人创作者写初稿的编辑助手。"
    "写稿必须严格围绕给定的核心观点，只能使用已关联的素材摘录作为事实来源，"
    "不得引入素材之外的新事实。输出为若干个自然段。"
)

MIN_CANDIDATE_CHARS = 20


class GeneratedDraft:
    """Deterministic review verdict over a raw candidate."""

    def __init__(self, blocks: list[dict], plain_text: str) -> None:
        self.blocks = blocks
        self.plain_text = plain_text
        self.rejected_reason: str | None = None
        self._review()

    def _review(self) -> None:
        stripped = self.plain_text.strip()
        if len(stripped) < MIN_CANDIDATE_CHARS:
            self.rejected_reason = "candidate-too-short"
        elif not any(block.get("text", "").strip() for block in self.blocks):
            self.rejected_reason = "candidate-empty"

    @property
    def accepted(self) -> bool:
        return self.rejected_reason is None


def build_consumer_graph(*, provider: LLMProvider, core_idea: str, intent: str, excerpts: list[dict], base_revision: int):
    """Build the one-shot generation graph for a single candidate request.

    The graph is built per request: consumer generation is a bounded flow
    (no interrupt nodes), so per-request construction keeps the state
    ownership explicit and the graph trivially inspectable in tests.
    """

    state_schema = {
        "core_idea": str,
        "intent": str,
        "excerpts": list,
        "base_revision": int,
        "raw_text": str,
        "candidate": Any,
        "error": Any,
        "usage": Any,
    }

    async def collect(state: dict) -> dict:
        return {
            "core_idea": core_idea,
            "intent": intent,
            "excerpts": excerpts,
            "base_revision": base_revision,
        }

    def _user_prompt() -> str:
        excerpt_lines = "\n".join(f"- {e.get('excerpt_text', '')}" for e in excerpts) or "（暂无关联素材）"
        return (
            f"核心观点：{core_idea}\n写作意图：{intent or '自由写作'}\n"
            f"已关联素材摘录（事实只能来自这里）：\n{excerpt_lines}\n\n"
            "请写出一篇完整初稿。"
        )

    async def generate(state: dict) -> dict:
        try:
            result = await provider.generate(system=SYSTEM_PROMPT, prompt=_user_prompt(), prompt_version=PROMPT_VERSION)
            return {
                "raw_text": result.content,
                "error": None,
                "usage": {
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "model": result.model,
                },
            }
        except ProviderExecutionError as error:
            return {"raw_text": "", "error": {"code": "PROVIDER_FAILED", "message": str(error), "retryable": error.retryable}}

    async def review(state: dict) -> dict:
        blocks = [
            {"block_id": f"b{index + 1}", "block_type": "paragraph", "text": paragraph}
            for index, paragraph in enumerate(state["raw_text"].split("\n"))
            if paragraph.strip()
        ]
        plain_text = "\n".join(block["text"] for block in blocks)
        candidate = GeneratedDraft(blocks, plain_text)
        if not candidate.accepted:
            return {"candidate": None, "error": {"code": "CANDIDATE_REJECTED", "message": candidate.rejected_reason, "retryable": True}}
        return {"candidate": {"blocks": candidate.blocks, "plain_text": candidate.plain_text, "prompt_version": PROMPT_VERSION}}

    graph = StateGraph(state_schema)
    graph.add_node("collect_linked_excerpts", collect)
    graph.add_node("generate_draft", generate)
    graph.add_node("review_draft", review)
    graph.add_node("persist_candidate", lambda state: {})
    graph.add_edge(START, "collect_linked_excerpts")
    graph.add_edge("collect_linked_excerpts", "generate_draft")
    graph.add_edge("generate_draft", "review_draft")
    graph.add_edge("review_draft", "persist_candidate")
    graph.add_edge("persist_candidate", END)
    return graph.compile()


class GraphCandidateGenerator:
    """CandidateGenerator port implementation backed by consumer_graph."""

    def __init__(self, *, provider: LLMProvider) -> None:
        self._provider = provider

    async def generate(self, *, core_idea: str, intent: str, excerpts: list[dict], base_revision: int, usage_out: dict | None = None) -> dict:
        graph = build_consumer_graph(
            provider=self._provider,
            core_idea=core_idea,
            intent=intent,
            excerpts=excerpts,
            base_revision=base_revision,
        )
        result = await graph.ainvoke(
            {
                "core_idea": core_idea,
                "intent": intent,
                "excerpts": excerpts,
                "base_revision": base_revision,
                "raw_text": "",
                "candidate": None,
                "error": None,
                "usage": None,
            }
        )
        if result.get("error"):
            error = result["error"]
            raise RuntimeError(f"candidate generation failed: {error['code']} {error['message']}")
        candidate = result["candidate"]
        if candidate is None:
            raise RuntimeError("candidate generation failed: no candidate produced")
        if usage_out is not None and isinstance(result.get("usage"), dict):
            usage_out.update(result["usage"])
        return candidate
