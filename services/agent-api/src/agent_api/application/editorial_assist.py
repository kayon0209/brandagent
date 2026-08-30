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


class ActionNotSupported(ValueError):
    def __init__(self, action: str) -> None:
        super().__init__(f"action must be one of {ACTIONS}, got {action}")
        self.action = action


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

        draft = await self._draft(principal, task_id)
        block_text = self._block_text(draft["document"], block_id)
        if block_text is None:
            raise NotFoundError(f"block {block_id} not found in the draft")
        # anchor verification: client offsets are authoritative when sent;
        # the server recomputes the slice and compares, never plain_text.find
        if start_offset is not None and end_offset is not None:
            expected = block_text[start_offset : end_offset + 1]
            if expected != selected_text:
                raise SelectionStale("选区与当前稿件不一致，请重新选择")
        elif selected_text not in block_text:
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
    # accept
    # ------------------------------------------------------------------

    def _canonical_selection(self, suggestion: dict, draft: dict, block_text: str) -> str | None:
        """Resolve the selection against the CURRENT server document.

        Block-local offsets are authoritative (the client computed them
        against this very block); the raw selected text is only a legacy
        fallback for stores that did not persist offsets.
        """

        start = suggestion.get("start_offset")
        end = suggestion.get("end_offset")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start <= end < len(block_text):
            return block_text[start : end + 1]
        selected = suggestion.get("selected_text")
        if selected and selected in block_text:
            return selected
        return None

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
        if suggestion.get("task_id") != task_id:
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

        # canonical selection: block-local offsets first, raw text fallback
        block_text = block.get("text", "")
        selection = self._canonical_selection(suggestion, draft, block_text)
        if selection is None:
            raise SelectionStale("选区与当前稿件不一致，请重新生成建议")
        if selection_hash(selection) != suggestion["selected_text_hash"]:
            raise SelectionStale("选区校验失败")
        if selection not in block_text:
            raise SelectionStale("选区与当前稿件不一致，请重新生成建议")

        # replace within the block at the verified anchor (block-local
        # offset when present; first text occurrence otherwise), then
        # rebuild plain text from the same block text so the two surfaces
        # can never diverge.
        offset = suggestion.get("start_offset")
        if isinstance(offset, int) and block_text[offset : suggestion.get("end_offset", offset) + 1] == selection:
            occurrence_in_block = offset
        else:
            occurrence_in_block = block_text.find(selection)
            if occurrence_in_block < 0:
                raise SelectionStale("选区与当前稿件不一致，请重新生成建议")
        new_block_text = (
            block_text[:occurrence_in_block] + suggestion["suggested_text"] + block_text[occurrence_in_block + len(selection):]
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
