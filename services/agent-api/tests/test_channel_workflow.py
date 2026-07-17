import json

import pytest

from agent_api.application.channels import ChannelWorkflowService, FinalGateBlocked
from agent_api.domain.models import Channel
from agent_api.providers.base import LLMProvider, ModelCallResult


class Provider(LLMProvider):
    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        payload = json.loads(prompt)
        content = f"{payload['master_content']}\nCTA:{payload['channel']}"
        return ModelCallResult(
            json.dumps({"content": content, "claims": ["Verified capability"], "block_mappings": [{"master_position": 0, "channel_position": 0, "transformation_type": "style_adaptation"}]}),
            "fake", "fake-v1", prompt_version, 1, 1, 1, "estimated", 0,
        )


class Store:
    def __init__(self):
        self.master = {"content_version_id": "master-1", "content": "Verified capability", "immutable_hash": "a" * 64, "approval_status": "approved"}
        self.saved = {}
        self.approved = set()
        self.unsupported = []

    async def approved_master(self, workspace_id, task_id): return self.master
    async def channel_specs(self, workspace_id, channels): return {channel.value: {"version": "v1"} for channel in channels}
    async def save_variant(self, **payload):
        version_id = f"version-{payload['channel']}"
        self.saved[payload["channel"]] = {**payload, "content_version_id": version_id}
        return version_id
    async def persist_reviews(self, **payload):
        facts = payload["reviews"]["facts"]
        if not facts["passed"]:
            self.unsupported.append({"channel": payload["channel"]})
    async def approved_channel_versions(self, workspace_id, task_id): return {channel: item["content_version_id"] for channel, item in self.saved.items() if channel in self.approved}
    async def open_critical_issues(self, workspace_id, task_id): return []
    async def unsupported_lineage(self, workspace_id, task_id): return self.unsupported
    async def cross_channel_conflicts(self, workspace_id, task_id, channel_versions): return []
    async def create_final_requirement(self, **payload): return {"target_snapshot_hash": "b" * 64}
    async def current_variant(self, workspace_id, task_id, channel): return self.saved.get(channel)


class Validator:
    def __init__(self, unsupported=False): self.unsupported = unsupported

    async def validate(self, *, workspace_id, task_id, product_id, channel, content, claims):
        return {
            "format": {"passed": True, "issues": []},
            "facts": {"passed": not self.unsupported, "issues": ["unsupported_new_claim"] if self.unsupported else []},
            "brand": {"passed": True, "issues": []},
            "compliance": {"passed": True, "issues": []},
        }


@pytest.mark.asyncio
async def test_generates_each_channel_from_the_same_approved_master_with_lineage() -> None:
    store = Store()
    service = ChannelWorkflowService(store=store, provider=Provider(), validator=Validator())
    channels = list(Channel)
    result = await service.generate(
        workspace_id="workspace-1", task_id="task-1", actor_id="operator-1",
        product_id="product-1", channels=channels,
    )
    assert set(result) == {channel.value for channel in channels}
    assert {item["master_content_version_id"] for item in store.saved.values()} == {"master-1"}
    assert all(item["spec_version"] == "v1" for item in store.saved.values())
    assert all(item["block_mappings"][0]["master_position"] == 0 for item in store.saved.values())


@pytest.mark.asyncio
async def test_final_gate_blocks_unsupported_new_facts() -> None:
    store = Store()
    service = ChannelWorkflowService(store=store, provider=Provider(), validator=Validator(unsupported=True))
    await service.generate(
        workspace_id="workspace-1", task_id="task-1", actor_id="operator-1",
        product_id="product-1", channels=[Channel.WECHAT_WEBSITE],
    )
    store.approved.add(Channel.WECHAT_WEBSITE.value)
    with pytest.raises(FinalGateBlocked) as caught:
        await service.final_gate(
            workspace_id="workspace-1", task_id="task-1",
            required_channels=[Channel.WECHAT_WEBSITE],
        )
    assert caught.value.code == "UNSUPPORTED_NEW_FACTS"


@pytest.mark.asyncio
async def test_final_gate_requires_every_selected_channel_approval() -> None:
    store = Store()
    service = ChannelWorkflowService(store=store, provider=Provider(), validator=Validator())
    await service.generate(
        workspace_id="workspace-1", task_id="task-1", actor_id="operator-1",
        product_id="product-1", channels=[Channel.WECHAT_WEBSITE, Channel.MARKETING_EMAIL],
    )
    store.approved.add(Channel.WECHAT_WEBSITE.value)
    with pytest.raises(FinalGateBlocked) as caught:
        await service.final_gate(
            workspace_id="workspace-1", task_id="task-1",
            required_channels=[Channel.WECHAT_WEBSITE, Channel.MARKETING_EMAIL],
        )
    assert caught.value.code == "CHANNEL_APPROVAL_INCOMPLETE"


@pytest.mark.asyncio
async def test_targeted_revision_creates_child_only_for_selected_channel() -> None:
    store = Store()
    service = ChannelWorkflowService(store=store, provider=Provider(), validator=Validator())
    await service.generate(
        workspace_id="workspace-1", task_id="task-1", actor_id="operator-1",
        product_id="product-1", channels=[Channel.WECHAT_WEBSITE, Channel.MARKETING_EMAIL],
    )
    untouched = dict(store.saved[Channel.MARKETING_EMAIL.value])
    current = store.saved[Channel.WECHAT_WEBSITE.value]
    current["master_content_version_id"] = "master-1"
    current["content"] = "old"
    revised = await service.revise(
        workspace_id="workspace-1", task_id="task-1", actor_id="operator-1",
        product_id="product-1", channel=Channel.WECHAT_WEBSITE,
        instructions=["Adjust CTA only"],
    )
    assert revised["parent_version_id"] == "version-wechat_website"
    assert store.saved[Channel.MARKETING_EMAIL.value] == untouched
