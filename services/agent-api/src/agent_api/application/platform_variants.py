"""Consumer platform variants (upgrade plan task 11).

Splits the safe preview loop from high-risk publishing:

- preview/render require NO approval (C-end freedom);
- generate/regenerate are bound to the adopted master snapshot and only
  ever ADD channel versions — the master is immutable;
- idempotency key = master hash + channel + prompt version;
- a generation failure keeps the previous version and stays retryable;
- prepare_export pins the current snapshot; actual publishing keeps the
  fail-closed MCP approval path (out of scope here by design).
"""

from __future__ import annotations

from typing import Protocol

from agent_api.api.security import Principal
from agent_api.domain.errors import NotFoundError


ALLOWED_CONSUMER_CHANNELS = ("wechat_website", "xiaohongshu", "video_script_60s")


class VariantGenerationError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class GenerationFailed(VariantGenerationError):
    def __init__(self, channel: str, message: str) -> None:
        super().__init__("VARIANT_GENERATION_FAILED", f"{channel} 版本生成失败：{message}", retryable=True)
        self.channel = channel


class VariantChannelGenerator(Protocol):
    async def generate(self, *, channel: str, master_content: str, core_idea: str) -> dict: ...


class ConsumerVariantStore(Protocol):
    async def get_project(self, workspace_id: str, task_id: str) -> dict | None: ...
    async def active_master(self, workspace_id: str, task_id: str) -> dict | None: ...
    async def current_variant(self, workspace_id: str, task_id: str, channel: str) -> dict | None: ...
    async def save_variant(self, **payload) -> dict: ...
    async def append_event(self, event: dict) -> None: ...


_PROMPT_VERSION = "consumer-variant:v1"
_REGEN_PROMPT_VERSION = "consumer-variant:regen:v1"

_EVENT_GENERATED = "consumer.variant.generated.v1"
_EVENT_FAILED = "consumer.variant.failed.v1"

_SYSTEM_PROMPT = (
    "你是一位平台内容改写助手。基于给定母稿为指定平台改写内容，"
    "不得引入母稿之外的新事实或数字。输出 JSON：{\"content\": \"...\", \"claims\": [], \"block_mappings\": []}。"
)

def _numeric_claims(text: str) -> set[str]:
    """Numeric claims in text that need lineage support (fact source)."""

    import re

    pattern = re.compile(r"\d+%|\d+(?:\.\d+)?[万亿倍]")
    return set(pattern.findall(text))

_EVENT_GENERATED = "consumer.variant.generated.v1"
_EVENT_FAILED = "consumer.variant.failed.v1"


class ConsumerChannelGeneratorAdapter:
    """VariantChannelGenerator over the shared LLM provider.

    Enforces the lineage rule from the plan: any numeric claim in the
    output MUST trace back to the master content — a claim the master
    does not support rejects the whole generation attempt.
    """

    _PROMPT_VERSION = "consumer-channel-adapter:v1"

    def __init__(self, *, provider) -> None:
        self._provider = provider

    async def generate(self, *, channel: str, master_content: str, core_idea: str) -> dict:
        import json as _json

        from agent_api.providers.base import ProviderExecutionError

        try:
            result = await self._provider.generate(
                system=_SYSTEM_PROMPT,
                prompt=_json.dumps(
                    {"channel": channel, "master_content": master_content, "core_idea": core_idea},
                    ensure_ascii=False,
                ),
                prompt_version=self._PROMPT_VERSION,
            )
        except ProviderExecutionError as error:
            # never leak provider exceptions past the variant boundary
            # (live-stack audit: an unwrapped rejection surfaced as a 500)
            raise VariantGenerationError(
                error.code if error.code in {"MODEL_CALL_FAILED", "MODEL_TIMEOUT"} else "VARIANT_PROVIDER_FAILED",
                f"{channel} 版本生成暂时不可用",
                retryable=error.retryable,
            ) from error
        try:
            payload = _json.loads(result.content)
            content = str(payload["content"])
            claims = [str(claim) for claim in payload.get("claims", [])]
            block_mappings = list(payload.get("block_mappings", []))
        except (KeyError, TypeError, _json.JSONDecodeError) as error:
            raise VariantGenerationError(
                "VARIANT_OUTPUT_INVALID",
                f"{channel} 版本内容无法解析",
                retryable=True,
            ) from error
        unsupported = _numeric_claims(content) - _numeric_claims(master_content)
        if unsupported:
            raise VariantGenerationError(
                "UNSUPPORTED_FACTUAL_CLAIM",
                f"{channel} 版本包含来源外的新事实：{''.join(sorted(unsupported))}",
                retryable=False,
            )
        return {"content": content, "claims": claims, "block_mappings": block_mappings}


class PlatformVariantService:
    def __init__(self, *, store: ConsumerVariantStore, generator: VariantChannelGenerator, channels: tuple[str, ...]) -> None:
        self._store = store
        self._generator = generator
        self._channels = tuple(channels)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _master(self, principal: Principal, task_id: str) -> dict:
        master = await self._store.active_master(principal.workspace_id, task_id)
        if master is None:
            raise NotFoundError("先采用当前稿，再生成平台版本")
        return master

    async def _save(
        self,
        principal: Principal,
        task_id: str,
        master: dict,
        channel: str,
        result: dict,
        *,
        prompt_version: str = _PROMPT_VERSION,
    ) -> dict:
        return await self._store.save_variant(
            workspace_id=principal.workspace_id,
            task_id=task_id,
            channel=channel,
            content=result.get("content", ""),
            claims=result.get("claims", []),
            block_mappings=result.get("block_mappings", []),
            master_content_version_id=master["content_version_id"],
            master_snapshot_hash=master["immutable_hash"],
            prompt_version=prompt_version,
        )

    # ------------------------------------------------------------------
    # public interface
    # ------------------------------------------------------------------

    async def generate_variants(self, principal: Principal, task_id: str) -> dict:
        """Generate variants for the default consumer channels in one call."""

        master = await self._master(principal, task_id)
        channels: dict[str, dict] = {}
        for channel in self._channels:
            try:
                result = await self._generator.generate(
                    channel=channel,
                    master_content=master["content"],
                    core_idea="",
                )
                saved = await self._save(principal, task_id, master, channel, result)
                channels[channel] = {
                    "status": "ready",
                    "content_version_id": saved["content_version_id"],
                    "master_content_version_id": master["content_version_id"],
                    "idempotent": saved.get("idempotent", False),
                }
                await self._store.append_event(
                    {
                        "workspace_id": principal.workspace_id,
                        "task_id": task_id,
                        "event_type": _EVENT_GENERATED,
                        "data": {"channel": channel, "content_version_id": saved["content_version_id"]},
                    }
                )
            except VariantGenerationError as error:
                channels[channel] = {
                    "status": "failed",
                    "retryable": error.retryable,
                    "error_code": error.code,
                }
                await self._store.append_event(
                    {
                        "workspace_id": principal.workspace_id,
                        "task_id": task_id,
                        "event_type": _EVENT_FAILED,
                        "data": {"channel": channel, "error_code": error.code},
                    }
                )
        return {"channels": channels, "master_content_version_id": master["content_version_id"]}

    async def regenerate(self, principal: Principal, task_id: str, channel: str) -> dict:
        """Regenerate one channel: adds a NEW version, never mutates the master.

        Idempotency is request-replay scoped: the same master hash + channel
        + regen prompt version replays the same regenerated row.
        """

        master = await self._master(principal, task_id)
        try:
            result = await self._generator.generate(channel=channel, master_content=master["content"], core_idea="")
        except VariantGenerationError:
            raise
        saved = await self._save(principal, task_id, master, channel, result, prompt_version=_REGEN_PROMPT_VERSION)
        await self._store.append_event(
            {
                "workspace_id": principal.workspace_id,
                "task_id": task_id,
                "event_type": _EVENT_GENERATED,
                "data": {"channel": channel, "content_version_id": saved["content_version_id"], "regenerated": True},
            }
        )
        return {**saved, "status": "ready", "channel": channel}

    async def preview(self, principal: Principal, task_id: str) -> dict:
        """Safe preview: no approval, always available for THIS workspace's project."""

        if await self._store.get_project(principal.workspace_id, task_id) is None:
            raise NotFoundError(f"project {task_id} not found in this workspace")
        master = await self._store.active_master(principal.workspace_id, task_id)
        channels: dict[str, dict] = {}
        for channel in self._channels:
            current = await self._store.current_variant(principal.workspace_id, task_id, channel)
            if current is not None:
                channels[channel] = {
                    "content": current["content"],
                    "content_version_id": current["content_version_id"],
                    "master_content_version_id": current["master_content_version_id"],
                }
        return {
            "requires_approval": False,
            "master_content_version_id": master["content_version_id"] if master else None,
            "channels": channels,
        }

    async def prepare_export(self, principal: Principal, task_id: str) -> dict:
        """Pin the current snapshot for export; publishing stays fail-closed."""

        master = await self._master(principal, task_id)
        return {
            "master_snapshot_hash": master["immutable_hash"],
            "master_content_version_id": master["content_version_id"],
            "published": False,
            "requires_approval_to_publish": True,
        }
