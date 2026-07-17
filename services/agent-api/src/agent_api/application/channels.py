from __future__ import annotations

import json
from typing import Protocol

from agent_api.domain.models import Channel
from agent_api.providers.base import LLMProvider


class FinalGateBlocked(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ChannelStore(Protocol):
    async def approved_master(self, workspace_id: str, task_id: str) -> dict | None: ...
    async def channel_specs(self, workspace_id: str, channels: list[Channel]) -> dict[str, dict]: ...
    async def save_variant(self, **payload) -> str: ...
    async def persist_reviews(self, **payload) -> None: ...
    async def approved_channel_versions(self, workspace_id: str, task_id: str) -> dict[str, str]: ...
    async def open_critical_issues(self, workspace_id: str, task_id: str) -> list[dict]: ...
    async def unsupported_lineage(self, workspace_id: str, task_id: str) -> list[dict]: ...
    async def cross_channel_conflicts(self, workspace_id: str, task_id: str, channel_versions: dict[str, str]) -> list[dict]: ...
    async def create_final_requirement(self, **payload) -> dict: ...
    async def current_variant(self, workspace_id: str, task_id: str, channel: str) -> dict | None: ...


class ChannelValidator(Protocol):
    async def validate(
        self, *, workspace_id: str, task_id: str, product_id: str,
        channel: str, content: str, claims: list[str],
    ) -> dict[str, dict]: ...


class ChannelWorkflowService:
    def __init__(self, *, store: ChannelStore, provider: LLMProvider, validator: ChannelValidator) -> None:
        self._store = store
        self._provider = provider
        self._validator = validator

    async def generate(
        self, *, workspace_id: str, task_id: str, actor_id: str,
        product_id: str, channels: list[Channel],
    ) -> dict[str, dict]:
        master = await self._store.approved_master(workspace_id, task_id)
        if not master or master.get("approval_status") != "approved":
            raise FinalGateBlocked("MASTER_NOT_APPROVED", "Channel variants require an approved canonical master version.")
        specifications = await self._store.channel_specs(workspace_id, channels)
        missing = [channel.value for channel in channels if channel.value not in specifications]
        if missing:
            raise FinalGateBlocked("CHANNEL_SPEC_MISSING", f"Active channel specifications are missing: {', '.join(missing)}")

        generated: dict[str, dict] = {}
        for channel in channels:
            specification = specifications[channel.value]
            result = await self._provider.generate(
                system="Adapt the approved canonical master to one channel. Return JSON with content, claims, and block_mappings. Do not add unsupported facts.",
                prompt=json.dumps({
                    "master_content": master["content"],
                    "master_content_version_id": master["content_version_id"],
                    "master_snapshot_hash": master["immutable_hash"],
                    "channel": channel.value,
                    "channel_spec": specification,
                }, ensure_ascii=False),
                prompt_version=f"channel-{channel.value}-v1",
            )
            try:
                payload = json.loads(result.content)
                content = str(payload["content"])
                claims = [str(claim) for claim in payload.get("claims", [])]
                block_mappings = list(payload.get("block_mappings", []))
            except (KeyError, TypeError, json.JSONDecodeError) as error:
                raise FinalGateBlocked("CHANNEL_OUTPUT_INVALID", f"Generated {channel.value} output is not valid structured content.") from error
            reviews = await self._validator.validate(
                workspace_id=workspace_id,
                task_id=task_id,
                product_id=product_id,
                channel=channel.value,
                content=content,
                claims=claims,
            )
            version_id = await self._store.save_variant(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_id=actor_id,
                channel=channel.value,
                content=content,
                claims=claims,
                block_mappings=block_mappings,
                master_content_version_id=master["content_version_id"],
                master_snapshot_hash=master["immutable_hash"],
                spec_version=str(specification["version"]),
            )
            await self._store.persist_reviews(
                workspace_id=workspace_id,
                task_id=task_id,
                content_version_id=version_id,
                channel=channel.value,
                reviews=reviews,
            )
            generated[channel.value] = {
                "content_version_id": version_id,
                "source_master_version_id": master["content_version_id"],
                "spec_version": str(specification["version"]),
                "reviews_passed": all(bool(review.get("passed")) for review in reviews.values()),
            }
        return generated

    async def revise(
        self, *, workspace_id: str, task_id: str, actor_id: str, product_id: str,
        channel: Channel, instructions: list[str],
    ) -> dict:
        current = await self._store.current_variant(workspace_id, task_id, channel.value)
        master = await self._store.approved_master(workspace_id, task_id)
        specifications = await self._store.channel_specs(workspace_id, [channel])
        if not current or not master or current.get("master_content_version_id") != master.get("content_version_id"):
            raise FinalGateBlocked("CHANNEL_LINEAGE_INVALID", "The channel revision must remain attached to the current approved master.")
        specification = specifications.get(channel.value)
        if not specification:
            raise FinalGateBlocked("CHANNEL_SPEC_MISSING", "The active channel specification is unavailable.")
        result = await self._provider.generate(
            system="Revise only the affected channel blocks. Preserve all unaffected content, facts, citations, and canonical master lineage. Return structured JSON.",
            prompt=json.dumps({
                "master_content": master["content"], "current_content": current["content"],
                "channel": channel.value, "channel_spec": specification,
                "revision_instructions": instructions,
            }, ensure_ascii=False),
            prompt_version=f"channel-{channel.value}-revision-v1",
        )
        try:
            payload = json.loads(result.content)
            content = str(payload["content"])
            claims = [str(claim) for claim in payload.get("claims", [])]
            block_mappings = list(payload.get("block_mappings", []))
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise FinalGateBlocked("CHANNEL_OUTPUT_INVALID", "The targeted channel revision is not valid structured content.") from error
        reviews = await self._validator.validate(
            workspace_id=workspace_id, task_id=task_id, product_id=product_id,
            channel=channel.value, content=content, claims=claims,
        )
        version_id = await self._store.save_variant(
            workspace_id=workspace_id, task_id=task_id, actor_id=actor_id,
            channel=channel.value, content=content, claims=claims,
            block_mappings=block_mappings, master_content_version_id=master["content_version_id"],
            master_snapshot_hash=master["immutable_hash"], spec_version=str(specification["version"]),
            parent_version_id=current["content_version_id"], content_type="channel_revised",
        )
        await self._store.persist_reviews(
            workspace_id=workspace_id, task_id=task_id, content_version_id=version_id,
            channel=channel.value, reviews=reviews,
        )
        return {"content_version_id": version_id, "parent_version_id": current["content_version_id"], "channel": channel.value, "reviews_passed": all(bool(review.get("passed")) for review in reviews.values())}

    async def final_gate(
        self, *, workspace_id: str, task_id: str, required_channels: list[Channel],
    ) -> dict:
        approved = await self._store.approved_channel_versions(workspace_id, task_id)
        required = {channel.value for channel in required_channels}
        if set(approved) != required:
            raise FinalGateBlocked("CHANNEL_APPROVAL_INCOMPLETE", "Every selected channel must be approved before final approval.")
        unsupported = await self._store.unsupported_lineage(workspace_id, task_id)
        if unsupported:
            raise FinalGateBlocked("UNSUPPORTED_NEW_FACTS", "Unsupported new facts block final approval.")
        critical = await self._store.open_critical_issues(workspace_id, task_id)
        if critical:
            raise FinalGateBlocked("CRITICAL_ISSUES_OPEN", "Critical review issues must be resolved before final approval.")
        conflicts = await self._store.cross_channel_conflicts(workspace_id, task_id, approved)
        if conflicts:
            raise FinalGateBlocked("CROSS_CHANNEL_CONFLICT", "All selected channels must derive from the same approved master version.")
        return await self._store.create_final_requirement(
            workspace_id=workspace_id,
            task_id=task_id,
            channel_versions=approved,
        )
