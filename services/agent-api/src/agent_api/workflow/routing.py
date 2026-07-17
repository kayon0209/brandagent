from agent_api.domain.models import AgentState, TaskStatus


def route_after_brief_validation(state: AgentState) -> str:
    return "ask_for_clarification" if state.missing_fields else "retrieve_brand_context"


def route_after_master_reviews(state: AgentState) -> str:
    if state.master_reviews_passed:
        return "request_master_approval"
    if state.master_revision_count >= state.max_master_revisions:
        return "handle_max_revisions"
    return "revise_master_content"


def route_after_outline_decision(state: AgentState) -> str:
    if state.status == TaskStatus.CANCELLED:
        return "__end__"
    if state.outline_approved:
        return "write_master_content"
    if state.outline_approval_outcome == "reject":
        if state.outline_revision_count >= state.max_outline_revisions:
            return "handle_max_revisions"
        return "revise_master_outline"
    return "request_outline_approval"


def route_after_master_decision(state: AgentState) -> str:
    if state.status == TaskStatus.CANCELLED:
        return "__end__"
    if state.master_approved:
        return "__end__"
    if state.master_approval_outcome == "reject":
        if state.master_revision_count >= state.max_master_revisions:
            return "handle_max_revisions"
        return "revise_master_content"
    if state.master_approval_outcome == "pending":
        return "request_master_approval"
    return "request_master_approval"
