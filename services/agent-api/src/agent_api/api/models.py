from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_api.domain.models import Channel


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BriefInput(ApiModel):
    topic: str = Field(default="", max_length=500)
    brand_id: str | None = None
    product_id: str | None = None
    target_audience: str = Field(default="", max_length=2000)
    publishing_objective: str = Field(default="", max_length=2000)
    primary_channel: Channel | None = None
    desired_audience_action: str = Field(default="", max_length=1000)


class CreateTaskRequest(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    selected_channels: list[Channel] = Field(min_length=1)
    brief: BriefInput


class ClarificationRequest(ApiModel):
    answers: dict[str, object]

    @field_validator("answers")
    @classmethod
    def validate_answers(cls, answers: dict[str, object]) -> dict[str, object]:
        allowed = {
            "topic", "brand_id", "product_id", "target_audience",
            "publishing_objective", "primary_channel", "desired_audience_action",
        }
        if not answers or set(answers) - allowed:
            raise ValueError("Unsupported clarification field")
        normalized = dict(answers)
        for field in {"topic", "target_audience", "publishing_objective", "desired_audience_action"} & set(answers):
            value = answers[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a non-empty string")
        for field in {"brand_id", "product_id"} & set(answers):
            normalized[field] = str(UUID(str(answers[field])))
        if "primary_channel" in answers:
            normalized["primary_channel"] = Channel(str(answers["primary_channel"]))
        return normalized


class DecisionRequest(ApiModel):
    content_version_id: str | None = None
    target_snapshot_hash: str = Field(min_length=32, max_length=128)
    decision: str
    comment: str = Field(min_length=1, max_length=4000)


class ChannelRevisionRequest(ApiModel):
    instructions: list[str] = Field(min_length=1, max_length=20)

    @field_validator("instructions")
    @classmethod
    def validate_instructions(cls, instructions: list[str]) -> list[str]:
        if any(not instruction.strip() or len(instruction) > 1000 for instruction in instructions):
            raise ValueError("Revision instructions must be non-empty and at most 1000 characters")
        return instructions


class ExportRequest(ApiModel):
    decision_id: str
    target_snapshot_hash: str = Field(min_length=64, max_length=64)
    formats: list[str] = Field(default_factory=lambda: ["json", "markdown"], min_length=1)

    @field_validator("formats")
    @classmethod
    def validate_formats(cls, formats: list[str]) -> list[str]:
        allowed = {"json", "markdown", "docx"}
        if set(formats) - allowed:
            raise ValueError("Unsupported export format")
        return sorted(set(formats))


class PreviewRequest(ApiModel):
    decision_id: str
    target_snapshot_hash: str = Field(min_length=64, max_length=64)


class SuccessResponse(ApiModel):
    success: bool = True
    data: dict[str, Any]


class ErrorDetail(ApiModel):
    code: str
    message: str


class ErrorResponse(ApiModel):
    success: bool = False
    error: ErrorDetail
