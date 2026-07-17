from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class Channel(StrEnum):
    WECHAT_WEBSITE = "wechat_website"
    XIAOHONGSHU = "xiaohongshu"
    VIDEO_SCRIPT_60S = "video_script_60s"
    MARKETING_EMAIL = "marketing_email"


class TaskStatus(StrEnum):
    DRAFT = "draft"
    VALIDATING_BRIEF = "validating_brief"
    WAITING_FOR_CLARIFICATION = "waiting_for_clarification"
    RESEARCHING = "researching"
    WAITING_FOR_OUTLINE_APPROVAL = "waiting_for_outline_approval"
    GENERATING_MASTER = "generating_master"
    REVIEWING_MASTER = "reviewing_master"
    WAITING_FOR_MASTER_APPROVAL = "waiting_for_master_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContentBrief(StrictModel):
    task_id: str
    workspace_id: str
    topic: str = ""
    brand_id: str | None = None
    product_id: str | None = None
    target_audience: str = ""
    publishing_objective: str = ""
    primary_channel: Channel | None = None
    selected_derivative_channels: list[Channel] = Field(default_factory=list)
    desired_audience_action: str = ""
    deadline: str | None = None
    target_length: int | None = None
    required_messages: list[str] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list)
    required_source_ids: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    tone: list[str] = Field(default_factory=list)
    brand_keywords: list[str] = Field(default_factory=list)
    reference_content_ids: list[str] = Field(default_factory=list)

    def missing_required_fields(self) -> list[str]:
        required = (
            "topic",
            "brand_id",
            "product_id",
            "target_audience",
            "publishing_objective",
            "primary_channel",
            "desired_audience_action",
        )
        return [field for field in required if not getattr(self, field)]


class ReviewSummary(StrictModel):
    review_type: str
    passed: bool
    critical_issues: list[str] = Field(default_factory=list)
    revision_instructions: list[str] = Field(default_factory=list)


class DecisionOutcome(StrictModel):
    valid: bool
    decision: str
    comment: str = ""


class AgentState(StrictModel):
    state_version: str = "2.0"
    task_id: str
    workspace_id: str
    user_id: str
    brief: ContentBrief | None = None
    missing_fields: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    clarification_history: list[dict[str, str]] = Field(default_factory=list)
    retrieved_source_ids: list[str] = Field(default_factory=list)
    verified_fact_ids: list[str] = Field(default_factory=list)
    brand_guideline_version: str | None = None
    channel_spec_versions: dict[str, str] = Field(default_factory=dict)
    content_strategy: dict[str, Any] | None = None
    master_outline_version_id: str | None = None
    outline_approved: bool = False
    outline_approval_outcome: str | None = None
    outline_revision_feedback: list[str] = Field(default_factory=list)
    outline_revision_count: int = 0
    max_outline_revisions: int = 3
    master_content_version_id: str | None = None
    master_review_results: list[ReviewSummary] = Field(default_factory=list)
    master_reviews_passed: bool = False
    master_revision_count: int = 0
    max_master_revisions: int = 3
    master_approved: bool = False
    master_approval_outcome: str | None = None
    master_revision_instructions: list[str] = Field(default_factory=list)
    selected_channels: list[Channel] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.DRAFT
    current_node: str | None = None
    cancellation_requested: bool = False
    error: dict[str, Any] | None = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
