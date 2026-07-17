from dataclasses import dataclass, field

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent_api.domain.models import AgentState, Channel, ContentBrief, DecisionOutcome, TaskStatus
from agent_api.providers.base import LLMProvider, ModelCallResult, ProviderExecutionError
from agent_api.workflow.graph import build_master_content_graph
from agent_api.workflow.checkpoint import checkpoint_config, checkpoint_serializer
from agent_api.workflow.services import WorkflowDependencies


class FakeProvider(LLMProvider):
    calls = 0

    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        self.calls += 1
        content = '{"audience":"enterprise IT"}' if prompt_version == "strategy-v1" else f"content:{prompt_version}"
        return ModelCallResult(content, "fake", "fake-v1", prompt_version, 1, 1, 1, "estimated", 0)


class FailOnceProvider(FakeProvider):
    def __init__(self) -> None:
        self.failed = False

    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        if not self.failed:
            self.failed = True
            raise ProviderExecutionError("MODEL_TIMEOUT", "Provider timed out", retryable=True)
        return await super().generate(system=system, prompt=prompt, prompt_version=prompt_version)


class FakeContext:
    async def retrieve(self, state: AgentState) -> dict[str, object]:
        return {
            "retrieved_source_ids": ["source-1"],
            "verified_fact_ids": ["fact-1"],
            "brand_guideline_version": "brand-v1",
            "channel_spec_versions": {"wechat_website": "channel-v1"},
        }


class EmptyContext:
    async def retrieve(self, state: AgentState) -> dict[str, object]:
        return {"verified_fact_ids": []}


class FakeDecisions:
    async def resolve(self, *, decision_id: str, **kwargs) -> DecisionOutcome:
        outcomes = {
            "outline-approved": DecisionOutcome(valid=True, decision="approve"),
            "outline-rejected": DecisionOutcome(valid=True, decision="reject", comment="Tighten section two"),
            "master-approved": DecisionOutcome(valid=True, decision="approve"),
            "master-rejected": DecisionOutcome(valid=True, decision="reject", comment="Revise the CTA block"),
        }
        return outcomes.get(decision_id, DecisionOutcome(valid=False, decision="invalid"))


@dataclass
class FakeVersions:
    saved: list[str] = field(default_factory=list)
    contents: dict[str, str] = field(default_factory=dict)
    writes: list[dict] = field(default_factory=list)

    async def save(self, **kwargs) -> str:
        version_id = f"version-{len(self.saved) + 1}"
        self.saved.append(version_id)
        self.contents[version_id] = kwargs["content"]
        self.writes.append(kwargs)
        return version_id

    async def get_content(self, *, state, version_id: str) -> str:
        return self.contents[version_id]


def complete_state() -> AgentState:
    brief = ContentBrief(
        task_id="task-1",
        workspace_id="workspace-1",
        topic="Nova X3 launch",
        brand_id="brand-1",
        product_id="product-1",
        target_audience="Enterprise IT",
        publishing_objective="Explain verified value",
        primary_channel=Channel.WECHAT_WEBSITE,
        desired_audience_action="Request demo",
    )
    return AgentState(
        task_id="task-1",
        workspace_id="workspace-1",
        user_id="operator-1",
        brief=brief,
        selected_channels=[Channel.WECHAT_WEBSITE],
    )


@pytest.mark.asyncio
async def test_graph_requires_two_distinct_human_approval_resumes() -> None:
    versions = FakeVersions()
    graph = build_master_content_graph(
        WorkflowDependencies(provider=FakeProvider(), context=FakeContext(), versions=versions, decisions=FakeDecisions()),
        checkpointer=InMemorySaver(serde=checkpoint_serializer()),
    )
    config = checkpoint_config(workspace_id="workspace-1", task_id="task-1")

    outline_wait = await graph.ainvoke(complete_state(), config)
    assert outline_wait["status"] == TaskStatus.WAITING_FOR_OUTLINE_APPROVAL
    assert outline_wait["__interrupt__"][0].value["scope"] == "outline"
    assert versions.saved == ["version-1"]

    master_wait = await graph.ainvoke(Command(resume={"decision_id": "outline-approved"}), config)
    assert master_wait["status"] == TaskStatus.WAITING_FOR_MASTER_APPROVAL
    assert master_wait["__interrupt__"][0].value["scope"] == "master"
    assert versions.saved == ["version-1", "version-2"]

    completed = await graph.ainvoke(Command(resume={"decision_id": "master-approved"}), config)
    assert completed["status"] == TaskStatus.COMPLETED
    assert completed["master_approved"] is True


@pytest.mark.asyncio
async def test_missing_authoritative_facts_stops_before_model_call() -> None:
    provider = FakeProvider()
    graph = build_master_content_graph(
        WorkflowDependencies(provider=provider, context=EmptyContext(), versions=FakeVersions(), decisions=FakeDecisions())
    )
    result = await graph.ainvoke(complete_state())
    assert result["status"] == TaskStatus.FAILED
    assert result["error"]["code"] == "AUTHORITATIVE_FACTS_MISSING"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_rejected_outline_creates_only_a_child_outline_revision() -> None:
    versions = FakeVersions()
    graph = build_master_content_graph(
        WorkflowDependencies(provider=FakeProvider(), context=FakeContext(), versions=versions, decisions=FakeDecisions()),
        checkpointer=InMemorySaver(serde=checkpoint_serializer()),
    )
    config = checkpoint_config(workspace_id="workspace-1", task_id="task-reject")
    await graph.ainvoke(complete_state(), config)
    result = await graph.ainvoke(Command(resume={"decision_id": "outline-rejected"}), config)
    assert result["outline_approved"] is False
    assert result["__interrupt__"][0].value["scope"] == "outline"
    assert versions.saved == ["version-1", "version-2"]
    assert versions.writes[1]["content_type"] == "master_outline"
    assert versions.writes[1]["parent_version_id"] == "version-1"


@pytest.mark.asyncio
async def test_rejected_master_creates_targeted_child_revision() -> None:
    versions = FakeVersions()
    graph = build_master_content_graph(
        WorkflowDependencies(provider=FakeProvider(), context=FakeContext(), versions=versions, decisions=FakeDecisions()),
        checkpointer=InMemorySaver(serde=checkpoint_serializer()),
    )
    config = checkpoint_config(workspace_id="workspace-1", task_id="task-master-reject")
    await graph.ainvoke(complete_state(), config)
    await graph.ainvoke(Command(resume={"decision_id": "outline-approved"}), config)
    revised = await graph.ainvoke(Command(resume={"decision_id": "master-rejected"}), config)
    assert revised["__interrupt__"][0].value["scope"] == "master"
    assert versions.writes[-1]["content_type"] == "master_revised"
    assert versions.writes[-1]["parent_version_id"] == "version-2"
    assert revised["master_revision_count"] == 1


@pytest.mark.asyncio
async def test_invalid_outline_evidence_reinterrupts_without_ending_thread() -> None:
    versions = FakeVersions()
    graph = build_master_content_graph(
        WorkflowDependencies(provider=FakeProvider(), context=FakeContext(), versions=versions, decisions=FakeDecisions()),
        checkpointer=InMemorySaver(serde=checkpoint_serializer()),
    )
    config = checkpoint_config(workspace_id="workspace-1", task_id="task-invalid-outline")
    await graph.ainvoke(complete_state(), config)
    retry_wait = await graph.ainvoke(Command(resume={"decision_id": "invalid"}), config)
    assert retry_wait["__interrupt__"][0].value["scope"] == "outline"
    master_wait = await graph.ainvoke(Command(resume={"decision_id": "outline-approved"}), config)
    assert master_wait["__interrupt__"][0].value["scope"] == "master"


@pytest.mark.asyncio
async def test_retry_continues_failed_provider_node_without_repeating_completed_nodes() -> None:
    provider = FailOnceProvider()
    versions = FakeVersions()
    graph = build_master_content_graph(
        WorkflowDependencies(provider=provider, context=FakeContext(), versions=versions, decisions=FakeDecisions()),
        checkpointer=InMemorySaver(serde=checkpoint_serializer()),
    )
    config = checkpoint_config(workspace_id="workspace-1", task_id="task-provider-retry")
    with pytest.raises(ProviderExecutionError):
        await graph.ainvoke(complete_state(), config)
    recovered = await graph.ainvoke(None, config)
    assert recovered["__interrupt__"][0].value["scope"] == "outline"
    assert versions.saved == ["version-1"]
