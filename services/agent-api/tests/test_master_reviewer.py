import pytest

from agent_api.domain.models import AgentState, Channel, ContentBrief
from agent_api.workflow.services import DeterministicMasterReviewer


def review_state() -> AgentState:
    return AgentState(
        task_id="task-1",
        workspace_id="workspace-1",
        user_id="operator-1",
        brief=ContentBrief(
            task_id="task-1",
            workspace_id="workspace-1",
            topic="Nova",
            brand_id="brand-1",
            product_id="product-1",
            target_audience="IT leaders",
            publishing_objective="Explain value",
            primary_channel=Channel.WECHAT_WEBSITE,
            desired_audience_action="Request demo",
            required_messages=["verified value"],
            forbidden_claims=["guaranteed savings"],
        ),
        retrieved_source_ids=["source-1"],
        verified_fact_ids=["fact-1"],
        brand_guideline_version="brand-v1",
    )


@pytest.mark.asyncio
async def test_master_review_returns_five_separate_review_dimensions() -> None:
    reviews = await DeterministicMasterReviewer().review(
        state=review_state(),
        content="Nova provides verified value with traceable evidence.",
    )
    assert [review.review_type for review in reviews] == [
        "factual", "citation", "brief_coverage", "brand", "compliance",
    ]
    assert all(review.passed for review in reviews)


@pytest.mark.asyncio
async def test_master_review_targets_missing_message_and_forbidden_claim() -> None:
    reviews = await DeterministicMasterReviewer().review(
        state=review_state(),
        content="Nova offers guaranteed savings.",
    )
    by_type = {review.review_type: review for review in reviews}
    assert by_type["brief_coverage"].passed is False
    assert by_type["compliance"].passed is False
    assert "Missing required message" in by_type["brief_coverage"].critical_issues[0]
    assert "Forbidden claim present" in by_type["compliance"].critical_issues[0]
