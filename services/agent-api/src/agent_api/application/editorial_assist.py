"""Editorial selection suggestions (upgrade plan task 9).

Anchored rewrites for the consumer manuscript: expand / replace_example /
shorten over the user's current selection. The provider only ever sees the
selection, its surrounding sentence, the core idea, and the project's
linked excerpts — never the whole workspace or material library.

Accept is atomic: the server verifies base_revision, block id, and the
selection hash against the canonical server document, replaces the exact
character range, writes a new draft revision, and records a user-action
event (explicitly NOT an enterprise approval).
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

from agent_api.api.security import Principal
from agent_api.domain.errors import ConflictError, NotFoundError
from agent_api.providers.base import ModelCallResult


ACTIONS = ("expand", "replace_example", "shorten")

SYSTEM_PROMPT = (
    "你是一位资深中文编辑。只改写用户选中的句子本身，保持人称、语气与立场不变。"
    "你只能依据给定的关联素材摘录补充事实；素材之外不得引入任何新的事实或数字。"
    "输出只包含改写后的句子，不要解释。"
)

_ACTION_INSTRUCTIONS = {
    "expand": "在保持原意的基础上把选中的句子写得更充实、更具体。",
    "replace_example": "为选中的句子换一个更贴切的例子或表达方式。",
    "shorten": "把选中的句子压缩到更精炼，去掉冗余。",
}

_CONTEXT_RADIUS = 120
_NUMERIC_CLAIM = re.compile(r"\d+%|\d+(?:\.\d+)?[万亿倍]")

# Free-intent panel (agentization P1): the user describes a rewrite intent
# in their own words; ONE classifier call maps it to one of the three
# supported actions — or refuses. Nothing outside the anchored pipeline can
# happen this way: a classified action re-enters the exact propose() path
# (anchor check, excerpt-only facts, numeric guard, suggestion row).
INTENT_SYSTEM_PROMPT = (
    "你是一个意图分类器。用户会给出对选中句子的改写意图。"
    "你必须且只能输出下面四个词之一，不要输出其他任何内容：\n"
    "expand — 用户想把句子写得更充实、更具体、补充细节\n"
    "replace_example — 用户想换一种说法、换个例子、换个表达方式\n"
    "shorten — 用户想精简、压缩、缩短句子\n"
    "refuse — 意图不属于以上任何一种（例如要求翻译、续写新内容、改变事实、删除全部内容等）"
)

INTENT_PROMPT_VERSION = "editorial-assist:intent:v1"


class ActionNotSupported(ValueError):
    def __init__(self, action: str) -> None:
        super().__init__(f"action must be one of {ACTIONS}, got {action}")
        self.action = action


class MissingAnchor(ValueError):
    def __init__(self, message: str = "选区缺少 blockId/startOffset/endOffset 完整锚点，不能生成建议") -> None:
        super().__init__(message)


def validate_selection_anchor(
    *,
    selected_text: object,
    block_id: str,
    base_revision: object,
    start_offset: object,
    end_offset: object,
) -> str:
    """Route-level P1-1 validation, shared contract for the propose route.

    Returns the validated selected_text; raises ValueError with a spoken
    message the route maps to 422 VALIDATION_ERROR. Kept OUT of the route
    handler so routing stays thin (project rule: no fat handlers).
    """
    if not isinstance(selected_text, str) or not block_id or not isinstance(base_revision, int):
        raise ValueError("selectedText, blockId and baseRevision (int) are required")
    if not isinstance(start_offset, int) or isinstance(start_offset, bool) or not isinstance(end_offset, int) or isinstance(end_offset, bool):
        raise ValueError("startOffset 和 endOffset（整数）必填，用于锚定选区")
    if start_offset < 0 or end_offset < start_offset:
        raise ValueError("startOffset/endOffset 必须满足 0 <= start <= end")
    if end_offset - start_offset + 1 != len(selected_text):
        raise ValueError("选区长度与 startOffset/endOffset 不一致，无法锚定")
    return selected_text


class SelectionStale(ConflictError):
    def __init__(self, message: str = "选区已过期，稿件在别处有更新") -> None:
        super().__init__(message)


class SuggestionStore(Protocol):
    async def get_draft(self, workspace_id: str, task_id: str) -> dict | None: ...
    async def save_draft(self, workspace_id: str, task_id: str, document: dict, plain_text: str, expected_revision: int) -> dict: ...
    async def get_excerpts_by_ids(self, workspace_id: str, excerpt_ids: list[str]) -> list[dict]: ...
    async def linked_excerpt_ids(self, workspace_id: str, task_id: str) -> list[str]: ...
    async def insert_suggestion(self, suggestion: dict) -> dict: ...
    async def get_suggestion(self, workspace_id: str, suggestion_id: str) -> dict | None: ...
    async def mark_accepted(self, workspace_id: str, suggestion_id: str, revision: int) -> None: ...
    async def append_event(self, event: dict) -> None: ...


class AssistProvider(Protocol):
    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult: ...


def selection_hash(text: str) -> str:
    return hashlib.sha256(f"selection:v1:{text}".encode("utf-8")).hexdigest()


def _context_sentence(plain_text: str, selected: str) -> str:
    index = plain_text.find(selected)
    if index < 0:
        return selected
    start = max(0, index - _CONTEXT_RADIUS)
    end = min(len(plain_text), index + len(selected) + _CONTEXT_RADIUS)
    return plain_text[start:end]

class EditorialAssistService:
    def __init__(self, *, store: SuggestionStore, provider: AssistProvider) -> None:
        self._store = store
        self._provider = provider

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _draft(self, principal: Principal, task_id: str) -> dict:
        draft = await self._store.get_draft(principal.workspace_id, task_id)
        if draft is None:
            raise NotFoundError(f"draft for project {task_id} not found")
        return draft

    async def _linked_excerpts(self, principal: Principal, task_id: str) -> list[dict]:
        excerpt_ids = await self._store.linked_excerpt_ids(principal.workspace_id, task_id)
        return await self._store.get_excerpts_by_ids(principal.workspace_id, excerpt_ids)

    @staticmethod
    def _block_text(document: dict, block_id: str) -> str | None:
        for block in document.get("blocks", []):
            if block.get("block_id") == block_id:
                return block.get("text", "")
        return None

    # ------------------------------------------------------------------
    # propose
    # ------------------------------------------------------------------

    async def propose(
        self,
        principal: Principal,
        task_id: str,
        *,
        action: str,
        selected_text: str,
        block_id: str,
        base_revision: int,
        start_offset: int | None = None,
        end_offset: int | None = None,
        usage_out: dict | None = None,
    ) -> dict | None:
        if action not in ACTIONS:
            raise ActionNotSupported(action)
        if not selected_text.strip():
            raise ValueError("selected_text is required")
        # P1-1: the block-local offset pair is the ONLY anchor. Proposing
        # without it (and letting persistence .find() the text later) is the
        # duplicate-text mis-targeting bug; refuse instead of guessing.
        if not isinstance(start_offset, int) or not isinstance(end_offset, int):
            raise MissingAnchor()

        draft = await self._draft(principal, task_id)
        block_text = self._block_text(draft["document"], block_id)
        if block_text is None:
            raise NotFoundError(f"block {block_id} not found in the draft")
        # anchor verification: the server recomputes the slice at the exact
        # client offsets and compares — never plain_text.find
        if not (0 <= start_offset <= end_offset < len(block_text)):
            # out-of-range offsets are a malformed request (422), not a
            # stale document (409): the range can never anchor at all
            raise MissingAnchor("选区偏移超出稿件范围，请重新选择")
        if block_text[start_offset : end_offset + 1] != selected_text:
            raise SelectionStale("选区与当前稿件不一致，请重新选择")

        excerpts = await self._linked_excerpts(principal, task_id)
        context = _context_sentence(draft["plain_text"], selected_text)
        excerpt_lines = "\n".join(f"- {e.get('excerpt_text', '')}" for e in excerpts) or "（无关联素材）"
        prompt = (
            f"改写任务：{_ACTION_INSTRUCTIONS[action]}\n\n"
            f"选中的句子：{selected_text}\n\n"
            f"上下文（仅供理解，不要改写）：…{context}…\n\n"
            f"可用素材摘录（唯一事实来源）：\n{excerpt_lines}\n\n"
            "请输出改写后的句子。"
        )

        result = await self._provider.generate(
            system=SYSTEM_PROMPT,
            prompt=prompt,
            prompt_version=f"editorial-assist:{action}:v1",
        )
        if usage_out is not None:
            usage_out.update(
                {
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "model": result.model,
                }
            )
        suggested_text = result.content.strip()
        if not suggested_text:
            return None

        # Guard: numeric claims are only allowed when a linked excerpt states them.
        if _NUMERIC_CLAIM.search(suggested_text):
            excerpt_text = " ".join(e.get("excerpt_text", "") for e in excerpts)
            for match in _NUMERIC_CLAIM.finditer(suggested_text):
                if match.group(0) not in excerpt_text:
                    return None  # unsupported numeric fact -> refuse to propose

        return await self._store.insert_suggestion(
            {
                "workspace_id": principal.workspace_id,
                "task_id": task_id,
                "action": action,
                "selected_text": selected_text,
                "selected_text_hash": selection_hash(selected_text),
                "suggested_text": suggested_text,
                "block_id": block_id,
                "start_offset": start_offset,
                "end_offset": end_offset,
                "base_revision": base_revision,
                "supporting_excerpt_ids": [e.get("excerpt_id") for e in excerpts],
                "prompt_version": f"editorial-assist:{action}:v1",
                "created_by_type": "model",
            }
        )

    # ------------------------------------------------------------------
    # free-intent propose (agentization P1: bounded intent panel)
    # ------------------------------------------------------------------

    async def propose_from_intent(
        self,
        principal: Principal,
        task_id: str,
        *,
        intent: str,
        selected_text: str,
        block_id: str,
        base_revision: int,
        start_offset: int | None = None,
        end_offset: int | None = None,
        usage_out: dict | None = None,
    ) -> dict:
        """Free-text rewrite intent -> one classified action -> propose().

        The classifier is deliberately strict: any intent that is not
        clearly one of the three supported rewrites is refused. A refused
        result carries the supported actions so the UI can guide the user
        back to the fixed palette instead of a dead end.
        """
        if not intent or not intent.strip():
            raise ValueError("intent is required")
        if len(intent) > 200:
            raise ValueError("intent 过长，请用一句话描述你想怎么改")

        intent_usage: dict = {}
        classified = await self._provider.generate(
            system=INTENT_SYSTEM_PROMPT,
            prompt=f"用户的改写意图：{intent.strip()}\n\n只输出 expand / replace_example / shorten / refuse 之一。",
            prompt_version=INTENT_PROMPT_VERSION,
        )
        if usage_out is not None:
            intent_usage = {
                "input_tokens": classified.input_tokens,
                "output_tokens": classified.output_tokens,
                "model": classified.model,
            }

        verdict = (classified.content or "").strip().lower()
        # tolerate tiny model format drift ("expand。", "intent: expand")
        verdict = verdict.removeprefix("intent:").strip(".。 \t")
        if verdict not in ACTIONS:
            return {
                "status": "refused",
                "reason": "unsupported_intent",
                "supported_actions": list(ACTIONS),
                "intent_verdict": verdict[:40] or "empty",
                "usage": intent_usage,
            }

        suggestion = await self.propose(
            principal,
            task_id,
            action=verdict,
            selected_text=selected_text,
            block_id=block_id,
            base_revision=base_revision,
            start_offset=start_offset,
            end_offset=end_offset,
            usage_out=usage_out,
        )
        if suggestion is None:
            # propose() refused (e.g. unsupported numeric claim): surface as
            # refused, not a silent empty success
            return {
                "status": "refused",
                "reason": "content_guard",
                "supported_actions": list(ACTIONS),
                "usage": intent_usage,
            }
        return {"status": "proposed", "suggestion": suggestion, "usage": intent_usage}

    # ------------------------------------------------------------------
    # accept
    # ------------------------------------------------------------------

    def _canonical_selection(self, suggestion: dict, draft: dict, block_text: str) -> str | None:
        """Resolve the selection against the CURRENT server document.

        Block-local offsets are the ONLY anchor: the client computed them
        against this very block. Suggestions persisted without a complete
        offset pair (legacy rows) have no anchor — return None so accept
        fails closed with a stale conflict instead of guessing position.
        """

        start = suggestion.get("start_offset")
        end = suggestion.get("end_offset")
        if not isinstance(start, int) or not isinstance(end, int):
            return None
        if not (0 <= start <= end < len(block_text)):
            return None
        return block_text[start : end + 1]

    async def accept(
        self,
        principal: Principal,
        task_id: str,
        suggestion_id: str,
        *,
        base_revision: int,
    ) -> dict:
        suggestion = await self._store.get_suggestion(principal.workspace_id, suggestion_id)
        if suggestion is None:
            raise NotFoundError(f"suggestion {suggestion_id} not found")
        # str() both sides: psycopg hands back task_id as a UUID object while the
        # route passes the URL string (same live-stack finding as apply_candidate).
        if str(suggestion.get("task_id")) != str(task_id):
            # in-workspace tenancy: a suggestion must belong to THIS project
            raise NotFoundError(f"suggestion {suggestion_id} does not belong to project {task_id}")
        if suggestion.get("status") == "accepted":
            return {"idempotent": True, "suggestion_id": suggestion_id, "revision": base_revision}

        # fresh draft guard
        draft = await self._draft(principal, task_id)
        if draft["revision"] != base_revision or suggestion["base_revision"] != draft["revision"]:
            raise SelectionStale()

        block = next(
            (b for b in draft["document"].get("blocks", []) if b.get("block_id") == suggestion["block_id"]),
            None,
        )
        if block is None:
            raise SelectionStale("选区所在段落已不存在")

        # canonical selection: block-local offsets are the only anchor; a
        # suggestion without a complete offset pair can never be accepted
        block_text = block.get("text", "")
        selection = self._canonical_selection(suggestion, draft, block_text)
        if selection is None:
            raise SelectionStale("选区与当前稿件不一致，请重新生成建议")
        if selection_hash(selection) != suggestion["selected_text_hash"]:
            raise SelectionStale("选区校验失败")

        # replace at the exact verified offset range — never .find(), which
        # mis-targets when the same sentence appears more than once
        start = suggestion["start_offset"]
        end = suggestion["end_offset"]
        new_block_text = (
            block_text[:start] + suggestion["suggested_text"] + block_text[end + 1:]
        )
        new_blocks = [
            {**b, "text": new_block_text} if b.get("block_id") == suggestion["block_id"] else b
            for b in draft["document"].get("blocks", [])
        ]
        new_plain = "\n".join(b.get("text", "") for b in new_blocks)
        new_document = {"blocks": new_blocks}
        try:
            saved = await self._store.save_draft(
                principal.workspace_id,
                task_id,
                new_document,
                new_plain,
                expected_revision=draft["revision"],
            )
        except ConflictError as error:
            raise SelectionStale() from error
        await self._store.mark_accepted(principal.workspace_id, suggestion_id, saved["revision"])
        await self._store.append_event(
            {
                "workspace_id": principal.workspace_id,
                "task_id": task_id,
                "event_type": "consumer.suggestion.accepted.v1",
                "data": {
                    "suggestion_id": suggestion_id,
                    "action": suggestion["action"],
                    "target_hash": suggestion["selected_text_hash"],
                    "revision": saved["revision"],
                },
            }
        )
        return {
            "idempotent": False,
            "suggestion_id": suggestion_id,
            "revision": saved["revision"],
            "plain_text": saved["plain_text"],
            "document": saved["document"],
        }
