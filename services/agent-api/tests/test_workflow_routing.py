from agent_api.domain.models import AgentState, TaskStatus
from agent_api.workflow.routing import route_after_brief_validation, route_after_master_reviews


def test_missing_fields_route_to_clarification() -> None:
    state = AgentState(task_id="task", workspace_id="workspace", user_id="user")
    state.missing_fields = ["product_id"]
    assert route_after_brief_validation(state) == "ask_for_clarification"


def test_valid_brief_routes_to_research() -> None:
    state = AgentState(task_id="task", workspace_id="workspace", user_id="user")
    assert route_after_brief_validation(state) == "retrieve_brand_context"


def test_revision_limit_routes_to_human_instead_of_looping() -> None:
    state = AgentState(task_id="task", workspace_id="workspace", user_id="user")
    state.master_reviews_passed = False
    state.master_revision_count = state.max_master_revisions
    assert route_after_master_reviews(state) == "handle_max_revisions"
    assert state.status is TaskStatus.DRAFT
