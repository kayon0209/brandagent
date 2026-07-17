from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent_api.domain.models import AgentState, TaskStatus, utc_now
from agent_api.workflow.routing import (
    route_after_brief_validation,
    route_after_master_decision,
    route_after_master_reviews,
    route_after_outline_decision,
)
from agent_api.workflow.services import DeterministicMasterReviewer, WorkflowDependencies
from agent_api.mcp.client import MCPExecutionError


def _public_error(code: str, message: str, node: str, recoverable: bool) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "failed_node": node,
        "recoverable": recoverable,
        "saved_work_safe": True,
        "requires_human": True,
    }


def build_master_content_graph(dependencies: WorkflowDependencies, *, checkpointer: Any = None):
    async def transition(state: AgentState, updates: dict[str, Any], event_type: str) -> dict[str, Any]:
        if dependencies.runtime:
            await dependencies.runtime.persist_transition(state, updates, event_type)
        return updates

    async def cancelled(state: AgentState) -> dict[str, Any] | None:
        if dependencies.runtime and await dependencies.runtime.is_cancelled(state):
            return {"status": TaskStatus.CANCELLED, "cancellation_requested": True, "current_node": "cancel_task", "error": None}
        return None

    async def validate_brief(state: AgentState) -> dict[str, Any]:
        missing = state.brief.missing_required_fields() if state.brief else ["brief"]
        return await transition(state, {
            "missing_fields": missing,
            "status": TaskStatus.WAITING_FOR_CLARIFICATION if missing else TaskStatus.RESEARCHING,
            "current_node": "validate_brief",
            "updated_at": utc_now(),
        }, "brief_parsed")

    async def ask_for_clarification(state: AgentState) -> dict[str, Any]:
        questions = [f"Please provide {field.replace('_', ' ')}." for field in state.missing_fields]
        return await transition(state, {
            "clarification_questions": questions,
            "status": TaskStatus.WAITING_FOR_CLARIFICATION,
            "current_node": "ask_for_clarification",
        }, "clarification_required")

    async def wait_for_clarification(state: AgentState) -> dict[str, Any]:
        answers = interrupt(
            {
                "type": "clarification_required",
                "task_id": state.task_id,
                "questions": state.clarification_questions,
            }
        )
        if not isinstance(answers, dict) or state.brief is None:
            return {"error": _public_error("INVALID_CLARIFICATION", "Clarification answers are invalid.", "wait_for_clarification", True)}
        allowed = set(state.brief.model_fields)
        allowed = allowed.intersection(state.missing_fields) - {"task_id", "workspace_id"}
        updates = {key: value for key, value in answers.items() if key in allowed}
        brief = state.brief.model_validate({**state.brief.model_dump(), **updates})
        history = [*state.clarification_history]
        for field, value in updates.items():
            history.append({"question": field, "answer": str(value), "answered_at": utc_now()})
        return {"brief": brief, "clarification_history": history, "current_node": "wait_for_clarification"}

    async def retrieve_brand_context(state: AgentState) -> dict[str, Any]:
        if stopped := await cancelled(state):
            return stopped
        try:
            context = await dependencies.context.retrieve(state)
        except MCPExecutionError as error:
            return await transition(state, {
                "status": TaskStatus.FAILED,
                "error": _public_error(error.code, str(error), "retrieve_brand_context", error.retryable),
                "current_node": "retrieve_brand_context",
            }, "error")
        if not context.get("verified_fact_ids"):
            return await transition(state, {
                "status": TaskStatus.FAILED,
                "error": _public_error("AUTHORITATIVE_FACTS_MISSING", "Authoritative product facts are required.", "retrieve_brand_context", True),
                "current_node": "retrieve_brand_context",
            }, "error")
        return await transition(state, {
            "retrieved_source_ids": list(context.get("retrieved_source_ids", [])),
            "verified_fact_ids": list(context.get("verified_fact_ids", [])),
            "brand_guideline_version": context.get("brand_guideline_version"),
            "channel_spec_versions": dict(context.get("channel_spec_versions", {})),
            "current_node": "retrieve_brand_context",
        }, "sources_retrieved")

    async def plan_content_strategy(state: AgentState) -> dict[str, Any]:
        if stopped := await cancelled(state):
            return stopped
        result = await dependencies.provider.generate(
            system="Return concise JSON only. Do not reveal hidden reasoning.",
            prompt=f"Create a content strategy for: {state.brief.model_dump_json() if state.brief else '{}'}",
            prompt_version="strategy-v1",
        )
        try:
            strategy = json.loads(result.content)
        except json.JSONDecodeError:
            strategy = {"summary": result.content}
        return {"content_strategy": strategy, "current_node": "plan_content_strategy"}

    async def generate_master_outline(state: AgentState) -> dict[str, Any]:
        if stopped := await cancelled(state):
            return stopped
        result = await dependencies.provider.generate(
            system="Write a factual outline grounded only in supplied verified fact IDs.",
            prompt=json.dumps({"brief": state.brief.model_dump() if state.brief else None, "fact_ids": state.verified_fact_ids, "strategy": state.content_strategy}, ensure_ascii=False),
            prompt_version="master-outline-v1",
        )
        version_id = await dependencies.versions.save(state=state, content_type="master_outline", content=result.content)
        return await transition(state, {"master_outline_version_id": version_id, "status": TaskStatus.WAITING_FOR_OUTLINE_APPROVAL, "current_node": "generate_master_outline"}, "outline_ready")

    async def request_outline_approval(state: AgentState) -> dict[str, Any]:
        return await transition(state, {
            "status": TaskStatus.WAITING_FOR_OUTLINE_APPROVAL,
            "current_node": "request_outline_approval",
            "outline_approval_outcome": None,
        }, "human_approval_required")

    async def wait_for_outline_approval(state: AgentState) -> dict[str, Any]:
        if stopped := await cancelled(state):
            return stopped
        decision = interrupt({"type": "human_approval_required", "scope": "outline", "version_id": state.master_outline_version_id})
        if not isinstance(decision, dict) or not isinstance(decision.get("decision_id"), str):
            return {
                "outline_approval_outcome": "invalid",
                "error": _public_error("INVALID_OUTLINE_DECISION", "Outline decision evidence is invalid.", "wait_for_outline_approval", True),
                "current_node": "wait_for_outline_approval",
            }
        outcome = await dependencies.decisions.resolve(
            decision_id=decision["decision_id"], state=state, scope="outline", version_id=state.master_outline_version_id,
        )
        if not outcome.valid:
            return {
                "outline_approval_outcome": "invalid",
                "error": _public_error("INVALID_OUTLINE_DECISION", "Outline decision does not match this version.", "wait_for_outline_approval", True),
                "current_node": "wait_for_outline_approval",
            }
        return {
            "outline_approved": outcome.decision == "approve",
            "outline_approval_outcome": outcome.decision,
            "outline_revision_feedback": [outcome.comment] if outcome.decision == "reject" and outcome.comment else [],
            "current_node": "wait_for_outline_approval",
            "error": None,
        }

    async def revise_master_outline(state: AgentState) -> dict[str, Any]:
        if stopped := await cancelled(state):
            return stopped
        if state.master_outline_version_id is None:
            return {"error": _public_error("OUTLINE_VERSION_MISSING", "The outline version is unavailable.", "revise_master_outline", False)}
        current_content = await dependencies.versions.get_content(state=state, version_id=state.master_outline_version_id)
        result = await dependencies.provider.generate(
            system="Revise only the outline sections identified by human feedback. Preserve supported sections and verified facts.",
            prompt=json.dumps({"current_outline": current_content, "feedback": state.outline_revision_feedback, "fact_ids": state.verified_fact_ids}, ensure_ascii=False),
            prompt_version="master-outline-revision-v1",
        )
        version_id = await dependencies.versions.save(
            state=state,
            content_type="master_outline",
            content=result.content,
            parent_version_id=state.master_outline_version_id,
        )
        return await transition(state, {
            "master_outline_version_id": version_id,
            "outline_revision_count": state.outline_revision_count + 1,
            "outline_approved": False,
            "outline_revision_feedback": [],
            "current_node": "revise_master_outline",
        }, "outline_ready")

    async def write_master_content(state: AgentState) -> dict[str, Any]:
        if stopped := await cancelled(state):
            return stopped
        if state.master_outline_version_id is None:
            return {"error": _public_error("OUTLINE_VERSION_MISSING", "The approved outline is unavailable.", "write_master_content", False)}
        outline_content = await dependencies.versions.get_content(state=state, version_id=state.master_outline_version_id)
        result = await dependencies.provider.generate(
            system="Write canonical master content. Use only verified facts and preserve citations.",
            prompt=json.dumps({"outline": outline_content, "fact_ids": state.verified_fact_ids}, ensure_ascii=False),
            prompt_version="master-content-v1",
        )
        version_id = await dependencies.versions.save(state=state, content_type="master_draft", content=result.content, parent_version_id=state.master_outline_version_id)
        return await transition(state, {"master_content_version_id": version_id, "status": TaskStatus.REVIEWING_MASTER, "current_node": "write_master_content"}, "master_generation_started")

    async def review_master_content(state: AgentState) -> dict[str, Any]:
        if state.master_content_version_id is None:
            return {"error": _public_error("MASTER_VERSION_MISSING", "The master content version is unavailable.", "review_master_content", False)}
        content = await dependencies.versions.get_content(state=state, version_id=state.master_content_version_id)
        reviewer = dependencies.reviewer or DeterministicMasterReviewer()
        reviews = await reviewer.review(state=state, content=content)
        passed = bool(reviews) and all(review.passed for review in reviews)
        instructions = [instruction for review in reviews for instruction in review.revision_instructions]
        if dependencies.runtime:
            await dependencies.runtime.persist_reviews(state, reviews)
        return await transition(state, {
            "master_review_results": reviews,
            "master_reviews_passed": passed,
            "master_revision_instructions": instructions,
            "status": TaskStatus.WAITING_FOR_MASTER_APPROVAL if passed else TaskStatus.REVIEWING_MASTER,
            "current_node": "review_master_content",
        }, "master_review_completed")

    async def revise_master_content(state: AgentState) -> dict[str, Any]:
        if stopped := await cancelled(state):
            return stopped
        if state.master_content_version_id is None:
            return {"error": _public_error("MASTER_VERSION_MISSING", "The master content version is unavailable.", "revise_master_content", False)}
        current_content = await dependencies.versions.get_content(state=state, version_id=state.master_content_version_id)
        result = await dependencies.provider.generate(
            system="Revise only the affected content blocks. Preserve unaffected human edits, citations, and verified facts.",
            prompt=json.dumps({"current_content": current_content, "instructions": state.master_revision_instructions, "fact_ids": state.verified_fact_ids}, ensure_ascii=False),
            prompt_version="master-content-revision-v1",
        )
        version_id = await dependencies.versions.save(
            state=state,
            content_type="master_revised",
            content=result.content,
            parent_version_id=state.master_content_version_id,
        )
        return await transition(state, {
            "master_content_version_id": version_id,
            "master_revision_count": state.master_revision_count + 1,
            "master_reviews_passed": False,
            "master_approved": False,
            "master_approval_outcome": None,
            "master_revision_instructions": [],
            "status": TaskStatus.REVIEWING_MASTER,
            "current_node": "revise_master_content",
        }, "master_generation_started")

    async def handle_max_revisions(state: AgentState) -> dict[str, Any]:
        return await transition(state, {"status": TaskStatus.FAILED, "error": _public_error("MAX_REVISIONS_REACHED", "The revision limit was reached and human intervention is required.", "handle_max_revisions", True), "current_node": "handle_max_revisions"}, "error")

    async def request_master_approval(state: AgentState) -> dict[str, Any]:
        return await transition(state, {
            "status": TaskStatus.WAITING_FOR_MASTER_APPROVAL,
            "current_node": "request_master_approval",
            "master_approval_outcome": None,
        }, "human_approval_required")

    async def wait_for_master_approval(state: AgentState) -> dict[str, Any]:
        if stopped := await cancelled(state):
            return stopped
        decision = interrupt({"type": "human_approval_required", "scope": "master", "version_id": state.master_content_version_id})
        if not isinstance(decision, dict) or not isinstance(decision.get("decision_id"), str):
            return {
                "master_approval_outcome": "invalid",
                "error": _public_error("INVALID_MASTER_DECISION", "Master decision evidence is invalid.", "wait_for_master_approval", True),
                "current_node": "wait_for_master_approval",
            }
        outcome = await dependencies.decisions.resolve(
            decision_id=decision["decision_id"], state=state, scope="master", version_id=state.master_content_version_id,
        )
        if not outcome.valid:
            return {
                "master_approval_outcome": "invalid",
                "error": _public_error("INVALID_MASTER_DECISION", "Master decision does not match this version.", "wait_for_master_approval", True),
                "current_node": "wait_for_master_approval",
            }
        approved = outcome.decision == "approve"
        updates = {
            "master_approved": approved,
            "master_approval_outcome": outcome.decision,
            "master_revision_instructions": [outcome.comment] if outcome.decision == "reject" and outcome.comment else [],
            "status": TaskStatus.COMPLETED if approved else TaskStatus.WAITING_FOR_MASTER_APPROVAL,
            "current_node": "wait_for_master_approval",
            "error": None,
        }
        event_type = "master_approved" if approved else "human_approval_required"
        return await transition(state, updates, event_type)

    graph = StateGraph(AgentState)
    graph.add_node("validate_brief", validate_brief)
    graph.add_node("ask_for_clarification", ask_for_clarification)
    graph.add_node("wait_for_clarification", wait_for_clarification)
    graph.add_node("retrieve_brand_context", retrieve_brand_context)
    graph.add_node("plan_content_strategy", plan_content_strategy)
    graph.add_node("generate_master_outline", generate_master_outline)
    graph.add_node("request_outline_approval", request_outline_approval)
    graph.add_node("wait_for_outline_approval", wait_for_outline_approval)
    graph.add_node("revise_master_outline", revise_master_outline)
    graph.add_node("write_master_content", write_master_content)
    graph.add_node("review_master_content", review_master_content)
    graph.add_node("revise_master_content", revise_master_content)
    graph.add_node("handle_max_revisions", handle_max_revisions)
    graph.add_node("request_master_approval", request_master_approval)
    graph.add_node("wait_for_master_approval", wait_for_master_approval)
    graph.add_edge(START, "validate_brief")
    graph.add_conditional_edges("validate_brief", route_after_brief_validation)
    graph.add_edge("ask_for_clarification", "wait_for_clarification")
    graph.add_edge("wait_for_clarification", "validate_brief")
    graph.add_conditional_edges("retrieve_brand_context", lambda state: END if state.error else "plan_content_strategy")
    graph.add_conditional_edges("plan_content_strategy", lambda state: END if state.status == TaskStatus.CANCELLED else "generate_master_outline")
    graph.add_conditional_edges("generate_master_outline", lambda state: END if state.status == TaskStatus.CANCELLED else "request_outline_approval")
    graph.add_edge("request_outline_approval", "wait_for_outline_approval")
    graph.add_conditional_edges("wait_for_outline_approval", route_after_outline_decision, {"write_master_content": "write_master_content", "revise_master_outline": "revise_master_outline", "handle_max_revisions": "handle_max_revisions", "request_outline_approval": "request_outline_approval", "__end__": END})
    graph.add_edge("revise_master_outline", "request_outline_approval")
    graph.add_conditional_edges("write_master_content", lambda state: END if state.status == TaskStatus.CANCELLED else "review_master_content")
    graph.add_conditional_edges("review_master_content", route_after_master_reviews)
    graph.add_edge("revise_master_content", "review_master_content")
    graph.add_edge("handle_max_revisions", END)
    graph.add_edge("request_master_approval", "wait_for_master_approval")
    graph.add_conditional_edges("wait_for_master_approval", route_after_master_decision, {"request_master_approval": "request_master_approval", "revise_master_content": "revise_master_content", "handle_max_revisions": "handle_max_revisions", "__end__": END})
    return graph.compile(checkpointer=checkpointer)
