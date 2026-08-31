"""Consumer draft generation service (upgrade plan task 8).

Generation flow with the revision guard the plan demands:

1. collect the project's core idea + linked excerpts (never the whole
   workspace, never unlinked materials);
2. produce a candidate content_version (master_revised, model,
   approval not_required) — the live draft is NOT touched;
3. apply_candidate does a second compare-and-swap: if the draft revision
   moved while the user was generating, the candidate stays available and
   the user draft wins.
"""

from __future__ import annotations

from typing import Protocol

from agent_api.api.security import Principal
from agent_api.domain.errors import ConflictError, NotFoundError


class ConsumerProjectReader(Protocol):
    async def get_project(self, principal: Principal, task_id: str) -> dict: ...


class ConsumerDraftWriter(Protocol):
    async def get_draft(self, workspace_id: str, task_id: str) -> dict | None: ...
    async def insert_candidate_version(self, workspace_id: str, task_id: str, plain_text: str, document: dict, *, prompt_version: str) -> dict: ...
    async def get_version(self, workspace_id: str, version_id: str) -> dict | None: ...
    async def save_draft(self, workspace_id: str, task_id: str, document: dict, plain_text: str, expected_revision: int) -> dict: ...
    async def append_event(self, event: dict) -> None: ...


class CandidateGenerator(Protocol):
    """Draft generation port; the LLM workflow is injected here."""

    async def generate(self, *, core_idea: str, intent: str, excerpts: list[dict], base_revision: int, usage_out: dict | None = None) -> dict: ...


_EVENT_CANDIDATE_READY = "consumer.draft.candidate_ready.v1"
_PROMPT_VERSION = "consumer-draft-gen:v1"


class DraftGenerationService:
    def __init__(self, *, store: ConsumerDraftWriter, generator: CandidateGenerator, projects: ConsumerProjectReader | None = None) -> None:
        self._store = store
        self._generator = generator
        self._projects = projects

    async def _context(self, principal: Principal, task_id: str) -> tuple[dict, dict, int]:
        if self._projects is None:
            raise NotFoundError(f"project {task_id} not found")
        project = await self._projects.get_project(principal, task_id)
        if project is None:
            raise NotFoundError(f"project {task_id} not found in this workspace")
        draft = await self._store.get_draft(principal.workspace_id, task_id)
        if draft is None:
            raise NotFoundError(f"draft for project {task_id} not found")
        return project, draft, int(draft["revision"])

    async def generate(self, principal: Principal, task_id: str, *, usage_out: dict | None = None) -> dict:
        """Run the generator and persist a candidate version (draft untouched)."""

        project, draft, revision = await self._context(principal, task_id)
        candidate = await self._generator.generate(
            core_idea=project["core_idea"],
            intent=project.get("writing_intent", ""),
            excerpts=project.get("linked_excerpts", []),
            base_revision=revision,
            usage_out=usage_out,
        )
        version = await self._store.insert_candidate_version(
            principal.workspace_id,
            task_id,
            candidate.get("plain_text", ""),
            {"blocks": candidate.get("blocks", [])},
            prompt_version=candidate.get("prompt_version", _PROMPT_VERSION),
        )
        await self._store.append_event(
            {
                "workspace_id": principal.workspace_id,
                "task_id": task_id,
                "event_type": _EVENT_CANDIDATE_READY,
                "data": {
                    "content_version_id": version["content_version_id"],
                    "base_revision": revision,
                },
            }
        )
        return {"candidate": version, "base_revision": revision}

    async def apply_candidate(self, principal: Principal, task_id: str, content_version_id: str, *, base_revision: int) -> dict | None:
        """Second compare-and-swap: apply only if the draft has not moved."""

        version = await self._store.get_version(principal.workspace_id, content_version_id)
        if version is None:
            raise NotFoundError(f"version {content_version_id} not found in this workspace")
        # str() both sides: psycopg returns task_id as a UUID object while the
        # route passes the URL string — a bare != made every real apply-candidate
        # 404 on PostgreSQL (the in-memory test stores keep strings, so the suite
        # stayed green while the live stack broke; live-stack audit finding).
        if str(version.get("task_id")) != str(task_id):
            # in-workspace tenancy: a candidate must belong to THIS project
            raise NotFoundError(f"version {content_version_id} does not belong to project {task_id}")
        try:
            return await self._store.save_draft(
                principal.workspace_id,
                task_id,
                {"blocks": version.get("structured_blocks", [])},
                version.get("content", ""),
                base_revision,
            )
        except ConflictError:
            return None
        # any non-conflict error (e.g. DB outage) must surface, not masquerade
        # as a stale revision 409 (code review P2)
