"""Consumer draft application service (upgrade plan task 8).

The draft is the live editable manuscript. Its ONLY concurrency rule is
revision compare-and-swap:

- autosave never creates content_version rows;
- adopt snapshots the draft at a revision into an immutable
  master_draft version (idempotent per revision);
- nothing ever overwrites a newer server draft with stale input.
"""

from __future__ import annotations

from typing import Protocol

from agent_api.api.security import Principal
from agent_api.domain.errors import ConflictError, NotFoundError


class ConsumerDraftStore(Protocol):
    """Persistence port for consumer drafts and their snapshot versions."""

    async def ensure_draft(self, workspace_id: str, task_id: str) -> dict: ...
    async def get_draft(self, workspace_id: str, task_id: str) -> dict | None: ...
    async def save_draft(self, workspace_id: str, task_id: str, document: dict, plain_text: str, expected_revision: int) -> dict: ...
    async def insert_snapshot_version(self, workspace_id: str, task_id: str, document: dict, plain_text: str, revision: int) -> dict: ...
    async def get_draft_snapshot_version(self, workspace_id: str, task_id: str, revision: int) -> dict | None: ...
    async def append_event(self, event: dict) -> None: ...


_EVENT_DRAFT_ADOPTED = "consumer.draft.adopted.v1"


def plain_text_of(document: dict) -> str:
    """Canonical plain text derived from a draft document."""
    blocks = document.get("blocks") if isinstance(document, dict) else None
    if not blocks:
        return ""
    return "\n\n".join(str(block.get("text", "")) for block in blocks).strip()


class DraftService:
    def __init__(self, *, store: ConsumerDraftStore) -> None:
        self._store = store

    async def _require_draft(self, principal: Principal, task_id: str) -> dict:
        draft = await self._store.get_draft(principal.workspace_id, task_id)
        if draft is None:
            raise NotFoundError(f"draft for project {task_id} not found")
        return draft

    async def get_or_create_draft(self, principal: Principal, task_id: str) -> dict:
        return await self._store.ensure_draft(principal.workspace_id, task_id)

    async def autosave(self, principal: Principal, task_id: str, document: dict, plain_text: str, *, expected_revision: int) -> dict | None:
        """Compare-and-swap save. Returns the new draft, or None on stale base."""

        try:
            return await self._store.save_draft(principal.workspace_id, task_id, document, plain_text, expected_revision)
        except ConflictError:
            return None

    async def adopt(self, principal: Principal, task_id: str, *, base_revision: int) -> dict:
        """Snapshot the current draft as an immutable master_draft version."""

        draft = await self._require_draft(principal, task_id)
        if draft["revision"] != base_revision:
            raise ConflictError("draft revision changed elsewhere; reload before adopting")
        existing = await self._store.get_draft_snapshot_version(principal.workspace_id, task_id, base_revision)
        if existing is not None:
            return {"version": existing, "idempotent": True}
        version = await self._store.insert_snapshot_version(
            principal.workspace_id,
            task_id,
            draft["document"],
            draft["plain_text"],
            base_revision,
        )
        await self._store.append_event(
            {
                "workspace_id": principal.workspace_id,
                "task_id": task_id,
                "event_type": _EVENT_DRAFT_ADOPTED,
                "data": {
                    "content_version_id": version["content_version_id"],
                    "base_revision": base_revision,
                },
            }
        )
        return {"version": version, "idempotent": False}
