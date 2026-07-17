from agent_api.domain.models import AgentState, Channel, ContentBrief, TaskStatus


def test_agent_state_round_trips_as_json_without_runtime_objects() -> None:
    brief = ContentBrief(
        task_id="10000000-0000-0000-0000-000000000001",
        workspace_id="00000000-0000-0000-0000-000000000001",
        topic="Nova X3 launch",
        brand_id="20000000-0000-0000-0000-000000000001",
        product_id="30000000-0000-0000-0000-000000000001",
        target_audience="Enterprise IT leaders",
        publishing_objective="Explain verified product value",
        primary_channel=Channel.WECHAT_WEBSITE,
        desired_audience_action="Request a product demo",
    )
    state = AgentState(
        task_id=brief.task_id,
        workspace_id=brief.workspace_id,
        user_id="operator-a",
        brief=brief,
        selected_channels=[Channel.WECHAT_WEBSITE],
        status=TaskStatus.DRAFT,
    )

    restored = AgentState.model_validate_json(state.model_dump_json())
    assert restored == state


def test_incomplete_brief_is_serializable_but_not_runnable() -> None:
    brief = ContentBrief(
        task_id="10000000-0000-0000-0000-000000000001",
        workspace_id="00000000-0000-0000-0000-000000000001",
        topic="",
    )
    assert brief.missing_required_fields() == [
        "topic",
        "brand_id",
        "product_id",
        "target_audience",
        "publishing_objective",
        "primary_channel",
        "desired_audience_action",
    ]
