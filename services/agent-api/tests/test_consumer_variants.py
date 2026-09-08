"""Consumer platform variants (upgrade plan task 11).

Vertical slices through PlatformVariantService: C-end preview needs no
approval, generation is bound to an adopted master snapshot, regenerate
only adds channel versions and never mutates the master, idempotency by
master hash + channel + prompt version, and failures keep the previous
version.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from agent_api.api.security import Principal
from agent_api.application.platform_variants import (
    GenerationFailed,
    PlatformVariantService,
    VariantGenerationError,
)
from agent_api.domain.errors import NotFoundError


def principal_for(workspace_id: str) -> Principal:
    return Principal(user_id="consumer-1", workspace_id=workspace_id, role="admin", experience="personal")


DEFAULT_CONSUMER_CHANNELS = ("wechat_website", "xiaohongshu", "video_script_60s")


class StubChannelGenerator:
    def __init__(self, output_by_channel: dict[str, str] | None = None) -> None:
        self.calls: list[dict] = []
        self.fail_channels: set[str] = set()
        self.output_by_channel = output_by_channel or {}

    async def generate(self, *, channel: str, master_content: str, core_idea: str, style_directives: str | None = None, usage_out: dict | None = None) -> dict:
        self.calls.append({"channel": channel, "master_content": master_content, "core_idea": core_idea})
        if channel in self.fail_channels:
            raise GenerationFailed(channel, "provider exploded")
        if usage_out is not None:
            usage_out.update({"input_tokens": 50, "output_tokens": 50, "model": "stub"})
        content = self.output_by_channel.get(channel, f"{channel} 版本内容：{master_content}")
        return {"content": content, "claims": [], "block_mappings": []}


class MemoryVariantStore:
    """In-memory ConsumerVariantStore with lineage guards."""

    def __init__(self) -> None:
        self.workspace_id = "ws-1"
        self.masters: dict[str, dict] = {}  # content_version_id -> master
        self.project_master: dict[str, str | None] = {}  # task_id -> master version id
        self.variants: dict[str, list[dict]] = {}  # (task_id, channel) -> versions (newest last)
        self.generation_counter = 0
        self.events: list[dict] = []

    async def get_project(self, workspace_id: str, task_id: str) -> dict | None:
        if workspace_id != self.workspace_id:
            return None
        return {"task_id": task_id} if task_id in self.project_master else None

    async def active_master(self, workspace_id: str, task_id: str) -> dict | None:
        version_id = self.project_master.get(task_id)
        if version_id is None or workspace_id != self.workspace_id:
            return None
        return self.masters.get(version_id)

    async def current_variant(self, workspace_id: str, task_id: str, channel: str) -> dict | None:
        versions = self.variants.get((task_id, channel), [])
        return versions[-1] if versions else None

    async def latest_reviews(self, workspace_id: str, task_id: str, content_version_id: str) -> list[dict]:
        # memory store holds no review rows; the postgres store owns them
        return []

    async def save_variant(self, *, workspace_id, task_id, channel, content, claims, block_mappings, master_content_version_id, master_snapshot_hash, prompt_version) -> dict:
        key = (task_id, channel)
        versions = self.variants.setdefault(key, [])
        # idempotency: same master hash + channel + prompt version replays
        for existing in versions:
            if (
                existing["master_snapshot_hash"] == master_snapshot_hash
                and existing["prompt_version"] == prompt_version
            ):
                return {**existing, "idempotent": True}
        self.generation_counter += 1
        version = {
            "content_version_id": f"cv-{self.generation_counter}",
            "task_id": task_id,
            "channel": channel,
            "content": content,
            "claims": claims,
            "block_mappings": block_mappings,
            "master_content_version_id": master_content_version_id,
            "master_snapshot_hash": master_snapshot_hash,
            "prompt_version": prompt_version,
            "created_by_type": "model",
        }
        versions.append(version)
        return {**version, "idempotent": False}

    async def append_event(self, event: dict) -> None:
        self.events.append(event)


def make_service(generator: StubChannelGenerator | None = None, *, master_text: str = "母稿内容") -> tuple[PlatformVariantService, MemoryVariantStore, StubChannelGenerator]:
    store = MemoryVariantStore()
    master_id = str(uuid4())
    store.masters[master_id] = {
        "content_version_id": master_id,
        "content": master_text,
        "immutable_hash": "hash-" + master_id[:8],
        "content_type": "master_draft",
    }
    store.project_master["task-1"] = master_id
    gen = generator or StubChannelGenerator()
    service = PlatformVariantService(store=store, generator=gen, channels=DEFAULT_CONSUMER_CHANNELS)
    return service, store, gen


@pytest.mark.asyncio
async def test_generate_variants_for_default_channels_requires_master() -> None:
    store = MemoryVariantStore()
    service = PlatformVariantService(store=store, generator=StubChannelGenerator(), channels=DEFAULT_CONSUMER_CHANNELS)
    with pytest.raises(NotFoundError):
        await service.generate_variants(principal_for("ws-1"), "task-1")


@pytest.mark.asyncio
async def test_preview_and_render_never_require_approval() -> None:
    service, store, _ = make_service()
    principal = principal_for("ws-1")
    # preview before any generation: allowed, simply empty
    preview = await service.preview(principal, "task-1")
    assert preview["requires_approval"] is False
    assert preview["channels"] == {}
    # generate then preview renders without any approval state
    generated = await service.generate_variants(principal, "task-1")
    assert set(generated["channels"].keys()) == set(DEFAULT_CONSUMER_CHANNELS)
    preview = await service.preview(principal, "task-1")
    assert preview["requires_approval"] is False
    for channel in DEFAULT_CONSUMER_CHANNELS:
        assert preview["channels"][channel]["content"]
        assert preview["channels"][channel]["master_content_version_id"] == store.project_master["task-1"]


@pytest.mark.asyncio
async def test_variant_generation_is_bound_to_the_adopted_master() -> None:
    service, store, gen = make_service()
    principal = principal_for("ws-1")
    await service.generate_variants(principal, "task-1")
    for call in gen.calls:
        assert call["master_content"] == "母稿内容"
        assert store.masters[store.project_master["task-1"]]["immutable_hash"]


@pytest.mark.asyncio
async def test_regenerate_adds_versions_and_never_mutates_master() -> None:
    service, store, gen = make_service()
    principal = principal_for("ws-1")
    first = await service.generate_variants(principal, "task-1")
    first_wechat = first["channels"]["wechat_website"]["content_version_id"]
    master_before = dict(store.masters[store.project_master["task-1"]])

    second = await service.regenerate(principal, "task-1", "wechat_website")
    second_wechat = second["content_version_id"]
    assert second_wechat != first_wechat, "regenerate must add a NEW channel version"

    # master untouched
    assert store.masters[store.project_master["task-1"]] == master_before
    # both versions exist, newest is current
    wechat_versions = store.variants[("task-1", "wechat_website")]
    assert len(wechat_versions) == 2
    assert wechat_versions[-1]["content_version_id"] == second_wechat


@pytest.mark.asyncio
async def test_generation_failure_keeps_the_previous_version() -> None:
    gen = StubChannelGenerator()
    gen.fail_channels.add("xiaohongshu")
    service, store, _ = make_service(gen)
    principal = principal_for("ws-1")
    result = await service.generate_variants(principal, "task-1")
    assert result["channels"]["wechat_website"]["status"] == "ready"
    assert result["channels"]["xiaohongshu"]["status"] == "failed"
    assert result["channels"]["xiaohongshu"].get("retryable") is True

    # retry path: failure resolved -> previous preserved, new version added
    gen.fail_channels.clear()
    retried = await service.regenerate(principal, "task-1", "xiaohongshu")
    assert retried["status"] == "ready"
    versions = store.variants[("task-1", "xiaohongshu")]
    assert len(versions) == 1, "failed attempts must not persist partial versions"


@pytest.mark.asyncio
async def test_unknown_variant_execution_marks_a_batch_for_estimated_settlement() -> None:
    class UnknownExecutionGenerator:
        async def generate(self, **kwargs) -> dict:
            raise VariantGenerationError(
                "MODEL_EXECUTION_UNKNOWN",
                "模型执行结果未知",
                retryable=False,
                execution_unknown=True,
            )

    service, store, _ = make_service()
    service = PlatformVariantService(
        store=store,
        generator=UnknownExecutionGenerator(),
        channels=("wechat_website",),
    )
    usage: dict = {}
    result = await service.generate_variants(principal_for("ws-1"), "task-1", usage_out=usage)

    assert result["channels"]["wechat_website"] == {
        "status": "failed",
        "retryable": False,
        "error_code": "MODEL_EXECUTION_UNKNOWN",
    }
    assert usage["execution_unknown"] is True
    with pytest.raises(VariantGenerationError) as caught:
        await service.regenerate(principal_for("ws-1"), "task-1", "wechat_website")
    assert caught.value.execution_unknown is True


@pytest.mark.asyncio
async def test_variant_adapter_preserves_a_lost_provider_response_as_unknown_execution() -> None:
    from agent_api.application.platform_variants import ConsumerChannelGeneratorAdapter
    from agent_api.providers.base import ProviderExecutionError

    class ResponseLossProvider:
        async def generate(self, **kwargs) -> dict:
            raise ProviderExecutionError(
                "MODEL_EXECUTION_UNKNOWN",
                "The provider may have executed the request but its response was lost.",
                retryable=False,
            )

    adapter = ConsumerChannelGeneratorAdapter(provider=ResponseLossProvider())
    with pytest.raises(VariantGenerationError) as caught:
        await adapter.generate(
            channel="wechat_website",
            master_content="母稿内容",
            core_idea="观点",
        )
    assert caught.value.code == "MODEL_EXECUTION_UNKNOWN"
    assert caught.value.execution_unknown is True
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_variant_adapter_preserves_a_confirmed_provider_execution() -> None:
    from agent_api.application.platform_variants import ConsumerChannelGeneratorAdapter
    from agent_api.providers.base import ProviderExecutionError

    class MalformedSuccessProvider:
        async def generate(self, **kwargs) -> dict:
            raise ProviderExecutionError(
                "MODEL_INVALID_RESPONSE",
                "The provider returned a malformed success response.",
                retryable=False,
                execution_confirmed=True,
            )

    adapter = ConsumerChannelGeneratorAdapter(provider=MalformedSuccessProvider())
    with pytest.raises(VariantGenerationError) as caught:
        await adapter.generate(
            channel="wechat_website",
            master_content="母稿内容",
            core_idea="观点",
        )
    assert caught.value.execution_confirmed is True


@pytest.mark.asyncio
async def test_replayed_generation_hits_idempotent_result_same_key() -> None:
    service, store, _ = make_service()
    principal = principal_for("ws-1")
    first = await service.generate_variants(principal, "task-1")
    # replaying the same generation (same master hash + channel + prompt version)
    again = await service.generate_variants(principal, "task-1")
    assert again["channels"]["wechat_website"]["content_version_id"] == first["channels"]["wechat_website"]["content_version_id"]
    assert again["channels"]["wechat_website"]["idempotent"] is True
    assert len(store.variants[("task-1", "wechat_website")]) == 1

    # an explicit regenerate carries a different prompt version -> a NEW row;
    # replaying THAT regenerate is idempotent against itself
    regen = await service.regenerate(principal, "task-1", "wechat_website")
    assert regen["idempotent"] is False
    regen_replay = await service.regenerate(principal, "task-1", "wechat_website")
    assert regen_replay["idempotent"] is True
    assert regen_replay["content_version_id"] == regen["content_version_id"]
    assert len(store.variants[("task-1", "wechat_website")]) == 2


@pytest.mark.asyncio
async def test_prepare_export_pins_the_current_snapshot_without_publishing() -> None:
    service, store, _ = make_service()
    principal = principal_for("ws-1")
    await service.generate_variants(principal, "task-1")
    export = await service.prepare_export(principal, "task-1")
    master = store.masters[store.project_master["task-1"]]
    assert export["master_snapshot_hash"] == master["immutable_hash"]
    assert export["published"] is False
    assert export["requires_approval_to_publish"] is True


@pytest.mark.asyncio
async def test_cross_workspace_master_reads_are_scoped() -> None:
    service, _, _ = make_service()
    intruder = Principal(user_id="intruder", workspace_id="ws-2", role="admin", experience="personal")
    with pytest.raises(NotFoundError):
        await service.generate_variants(intruder, "task-1")
    with pytest.raises(NotFoundError):
        await service.preview(intruder, "task-1")


@pytest.mark.asyncio
async def test_variant_with_unsupported_numeric_claim_is_rejected() -> None:
    """The lineage adapter refuses outputs with facts absent from the master."""

    import json
    from types import SimpleNamespace

    class ClaimyProvider:
        async def generate(self, *, system: str, prompt: str, prompt_version: str) -> dict:
            return SimpleNamespace(
                content=json.dumps({"content": "转化率提升了 300%，非常惊人。", "claims": [], "block_mappings": []}),
                provider="stub",
                model="stub",
                prompt_version=prompt_version,
                latency_ms=5,
                input_tokens=1,
                output_tokens=1,
                usage_source="none",
                retry_count=0,
            )

    from agent_api.application.platform_variants import ConsumerChannelGeneratorAdapter

    adapter = ConsumerChannelGeneratorAdapter(provider=ClaimyProvider())
    store = MemoryVariantStore()
    master_id = str(uuid4())
    store.masters[master_id] = {
        "content_version_id": master_id,
        "content": "母稿内容，不含任何数字。",
        "immutable_hash": "hash-" + master_id[:8],
    }
    store.project_master["task-1"] = master_id
    service = PlatformVariantService(store=store, generator=adapter, channels=DEFAULT_CONSUMER_CHANNELS)

    principal = principal_for("ws-1")
    result = await service.generate_variants(principal, "task-1")
    for channel in DEFAULT_CONSUMER_CHANNELS:
        assert result["channels"][channel]["status"] == "failed"
        assert result["channels"][channel]["error_code"] == "UNSUPPORTED_FACTUAL_CLAIM"
    # nothing persisted, no partial channel version
    assert store.variants == {}


@pytest.mark.asyncio
async def test_variant_numeric_claim_supported_by_master_passes() -> None:
    import json

    from types import SimpleNamespace

    class HonestProvider:
        async def generate(self, *, system: str, prompt: str, prompt_version: str) -> dict:
            return SimpleNamespace(
                content=json.dumps({"content": "转化率提升了 300%。", "claims": [], "block_mappings": []}),
                provider="stub",
                model="stub",
                prompt_version=prompt_version,
                latency_ms=5,
                input_tokens=1,
                output_tokens=1,
                usage_source="none",
                retry_count=0,
            )

    from agent_api.application.platform_variants import ConsumerChannelGeneratorAdapter

    adapter = ConsumerChannelGeneratorAdapter(provider=HonestProvider())
    store = MemoryVariantStore()
    master_id = str(uuid4())
    store.masters[master_id] = {
        "content_version_id": master_id,
        "content": "母稿提到转化率提升了 300%。",
        "immutable_hash": "hash-" + master_id[:8],
    }
    store.project_master["task-1"] = master_id
    service = PlatformVariantService(store=store, generator=adapter, channels=DEFAULT_CONSUMER_CHANNELS)
    principal = principal_for("ws-1")
    result = await service.generate_variants(principal, "task-1")
    assert all(result["channels"][c]["status"] == "ready" for c in DEFAULT_CONSUMER_CHANNELS)


# ---------------------------------------------------------------------
# 007: project-bound style report injects six-layer directives into
# variant generation; a lapsed/missing binding must never block it
# ---------------------------------------------------------------------

class StyleBindingStore:
    """Minimal ConsumerVariantStore with an optional style binding."""

    def __init__(self, *, style_report=None, bound=True) -> None:
        self.project = {"task_id": "t-1", "workspace_id": "ws-1", "core_idea": "观点", "active_master_version_id": "m-1"}
        if bound:
            self.project["preferred_style_report_id"] = "r-1"
        self.style_report = style_report

    async def get_project(self, workspace_id, task_id):
        return dict(self.project) if task_id == "t-1" else None

    async def active_master(self, workspace_id, task_id):
        return {"content_version_id": "m-1", "content": "主稿正文", "immutable_hash": "h" * 64}

    async def current_variant(self, workspace_id, task_id, channel):
        return None

    async def latest_reviews(self, workspace_id, task_id, content_version_id):
        return []

    async def save_variant(self, **payload):
        return {"content_version_id": "v-1", "idempotent": False}

    async def append_event(self, event):
        return None

    async def get_style_report(self, workspace_id, report_id):
        return dict(self.style_report) if self.style_report is not None and report_id == "r-1" else None


class DirectiveCaptureGenerator:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(self, *, channel: str, master_content: str, core_idea: str, style_directives: str | None = None, usage_out: dict | None = None) -> dict:
        self.calls.append({"channel": channel, "style_directives": style_directives})
        return {"plain_text": f"{channel} 版本"}


@pytest.mark.asyncio
async def test_bound_style_report_injects_directives_into_generation():
    report = {
        "report_id": "r-1",
        "layers": {
            "l1_language_dna": {"rules": ["句子平均 20 字", "多用第一人称"], "summary": "短句口语"},
            "l6_visual_guide": {"rules": [], "summary": "无法推断。"},
        },
    }
    store = StyleBindingStore(style_report=report)
    generator = DirectiveCaptureGenerator()
    service = PlatformVariantService(store=store, generator=generator, channels=("wechat_website",))
    await service.generate_variants(Principal(user_id="u-1", workspace_id="ws-1", role="admin", experience="personal"), "t-1")
    directives = generator.calls[0]["style_directives"]
    assert directives is not None
    assert "句子平均 20 字" in directives
    assert "语言 DNA" in directives
    # an uninferable layer contributes nothing — fake rules never reach prompts
    assert "视觉风格" not in directives


@pytest.mark.asyncio
async def test_lapsed_style_binding_never_blocks_generation():
    store = StyleBindingStore(style_report=None)  # stale reference, report gone
    generator = DirectiveCaptureGenerator()
    service = PlatformVariantService(store=store, generator=generator, channels=("wechat_website",))
    result = await service.generate_variants(Principal(user_id="u-1", workspace_id="ws-1", role="admin", experience="personal"), "t-1")
    assert result["channels"]["wechat_website"]["status"] == "ready"
    assert generator.calls[0]["style_directives"] is None


@pytest.mark.asyncio
async def test_unbound_project_generates_without_directives():
    store = StyleBindingStore(style_report={"report_id": "r-1", "layers": {}}, bound=False)
    generator = DirectiveCaptureGenerator()
    service = PlatformVariantService(store=store, generator=generator, channels=("wechat_website",))
    await service.generate_variants(Principal(user_id="u-1", workspace_id="ws-1", role="admin", experience="personal"), "t-1")
    assert generator.calls[0]["style_directives"] is None
