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
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        execution_unknown: bool = False,
        execution_confirmed: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.execution_unknown = execution_unknown
        self.execution_confirmed = execution_confirmed


class GenerationFailed(VariantGenerationError):
    def __init__(self, channel: str, message: str) -> None:
        super().__init__("VARIANT_GENERATION_FAILED", f"{channel} 版本生成失败：{message}", retryable=True)
        self.channel = channel


class VariantChannelGenerator(Protocol):
    async def generate(self, *, channel: str, master_content: str, core_idea: str, style_directives: str | None = None, usage_out: dict | None = None) -> dict: ...


class ConsumerVariantStore(Protocol):
    async def get_project(self, workspace_id: str, task_id: str) -> dict | None: ...
    async def active_master(self, workspace_id: str, task_id: str) -> dict | None: ...
    async def current_variant(self, workspace_id: str, task_id: str, channel: str) -> dict | None: ...
    async def latest_reviews(self, workspace_id: str, task_id: str, content_version_id: str) -> list[dict]: ...
    async def save_variant(self, **payload) -> dict: ...
    async def append_event(self, event: dict) -> None: ...
    async def get_style_report(self, workspace_id: str, report_id: str) -> dict | None: ...


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

    async def generate(self, *, channel: str, master_content: str, core_idea: str, style_directives: str | None = None, usage_out: dict | None = None) -> dict:
        import json as _json

        from agent_api.providers.base import ProviderExecutionError

        # 007: when the project has a bound style report, the six-layer
        # rules ride along as a constraint section — same contract fields,
        # prompt-only enrichment
        payload = {"channel": channel, "master_content": master_content, "core_idea": core_idea}
        if style_directives:
            payload["style_directives"] = style_directives
        try:
            result = await self._provider.generate(
                system=_SYSTEM_PROMPT,
                prompt=_json.dumps(payload, ensure_ascii=False),
                prompt_version=self._PROMPT_VERSION,
            )
        except ProviderExecutionError as error:
            # never leak provider exceptions past the variant boundary
            # (live-stack audit: an unwrapped rejection surfaced as a 500)
            raise VariantGenerationError(
                error.code if error.code == "MODEL_EXECUTION_UNKNOWN" else (
                    error.code if error.code in {"MODEL_CALL_FAILED", "MODEL_TIMEOUT"} else "VARIANT_PROVIDER_FAILED"
                ),
                f"{channel} 版本生成暂时不可用",
                retryable=error.retryable,
                execution_unknown=error.code == "MODEL_EXECUTION_UNKNOWN",
                execution_confirmed=error.execution_confirmed,
            ) from error
        if usage_out is not None:
            usage_out["input_tokens"] = (usage_out.get("input_tokens") or 0) + (result.input_tokens or 0)
            usage_out["output_tokens"] = (usage_out.get("output_tokens") or 0) + (result.output_tokens or 0)
            usage_out["model"] = result.model
            usage_out["model_executed"] = True
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

    async def _core_idea(self, principal: Principal, task_id: str) -> str:
        """The project's core idea is product truth: platform variants must
        preserve it (audit finding: it was hardcoded to an empty string)."""

        project = await self._store.get_project(principal.workspace_id, task_id)
        if project is None:
            raise NotFoundError(f"project {task_id} not found in this workspace")
        return str(project.get("core_idea") or "")

    async def _style_directives(self, principal: Principal, task_id: str) -> str | None:
        """007: if the project binds a distilled style report, flatten its
        six layers into one prompt constraint section. A lapsed reference
        (report deleted; FK SET NULL) or unreadable layers read as NO
        binding — style enrichment never blocks generation."""
        project = await self._store.get_project(principal.workspace_id, task_id)
        if project is None:
            return None
        report_id = project.get("preferred_style_report_id")
        if not report_id:
            return None
        try:
            report = await self._store.get_style_report(principal.workspace_id, str(report_id))
        except Exception:  # noqa: BLE001 — enrichment is best-effort
            return None
        if report is None:
            return None
        layers = report.get("layers") or {}
        sections = []
        layer_titles = {
            "l1_language_dna": "语言 DNA",
            "l2_structure_template": "结构模板",
            "l3_topic_logic": "选题逻辑",
            "l4_evidence_strategy": "素材策略",
            "l5_cognitive_frame": "认知框架",
            "l6_visual_guide": "视觉风格",
        }
        for key, title in layer_titles.items():
            layer = layers.get(key) or {}
            rules = [str(rule) for rule in layer.get("rules", []) if str(rule).strip()]
            summary = str(layer.get("summary", "")).strip()
            # an uninferable layer has no rules — its "无法推断" note is
            # not a constraint and must not enter the prompt
            if not rules:
                continue
            lines = [f"- {rule}" for rule in rules]
            if summary:
                lines.append(f"- 总体：{summary}")
            sections.append(f"【{title}】\n" + "\n".join(lines))
        if not sections:
            return None
        return "写作风格规则（请遵守以下约束改写，风格优先级高于默认语气）：\n" + "\n".join(sections)

    async def generate_variants(self, principal: Principal, task_id: str, *, usage_out: dict | None = None) -> dict:
        """Generate variants for the default consumer channels in one call."""

        master = await self._master(principal, task_id)
        core_idea = await self._core_idea(principal, task_id)
        style_directives = await self._style_directives(principal, task_id)
        channels: dict[str, dict] = {}
        for channel in self._channels:
            try:
                result = await self._generator.generate(
                    channel=channel,
                    master_content=master["content"],
                    core_idea=core_idea,
                    style_directives=style_directives,
                    usage_out=usage_out,
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
                if error.execution_unknown and usage_out is not None:
                    # One ledger entry covers this fan-out. A lost response
                    # for any channel means actual aggregate tokens are
                    # unknowable, so settle the reservation estimate rather
                    # than undercharging or refunding a possibly executed call.
                    usage_out["execution_unknown"] = True
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

    async def regenerate(self, principal: Principal, task_id: str, channel: str, *, usage_out: dict | None = None) -> dict:
        """Regenerate one channel: adds a NEW version, never mutates the master.

        Idempotency is request-replay scoped: the same master hash + channel
        + regen prompt version replays the same regenerated row.
        """

        master = await self._master(principal, task_id)
        core_idea = await self._core_idea(principal, task_id)
        try:
            result = await self._generator.generate(channel=channel, master_content=master["content"], core_idea=core_idea, usage_out=usage_out)
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
        """Safe preview: no approval, always available for THIS workspace's project.

        Includes the spoken-language pre-publish review bubbles mapped from
        the adopted master's deterministic review rows (the UI previously
        hard-wired an empty list, so real warnings could never appear)."""

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
        bubbles: list[dict] = []
        if master is not None:
            reviews = await self._store.latest_reviews(
                principal.workspace_id, task_id, master["content_version_id"]
            )
            from agent_api.application.consumer_reviews import ConsumerReviewMapper

            bubbles = ConsumerReviewMapper().map_bubbles(
                reviews,
                master_snapshot_hash=master["immutable_hash"],
                export_snapshot_hash=master["immutable_hash"],
            )
        return {
            "requires_approval": False,
            "master_content_version_id": master["content_version_id"] if master else None,
            "channels": channels,
            "review": {"bubbles": bubbles},
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
