from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .contracts import TOOL_CAPABILITIES
from .repository import ToolRejected
from .security import require_scope


CHANNELS = {"wechat_website", "xiaohongshu", "video_script_60s", "marketing_email"}


class BrandToolStore(Protocol):
    async def search_documents(self, workspace_id: str, query: str, limit: int) -> list[dict]: ...
    async def product_facts(self, workspace_id: str, product_id: str) -> list[dict]: ...
    async def brand_guidelines(self, workspace_id: str, brand_id: str) -> dict | None: ...
    async def channel_spec(self, workspace_id: str, channel: str) -> dict | None: ...
    async def save_version(self, workspace_id: str, task_id: str, content_type: str, content: str, parent_version_id: str | None, actor_id: str, idempotency_key: str, channel: str | None, master_content_version_id: str | None) -> tuple[dict, bool]: ...
    async def authorized_package(self, *, workspace_id: str, task_id: str, actor_id: str, decision_id: str, target_snapshot_hash: str, idempotency_key: str, action: str, allowed_types: tuple[str, ...], formats: list[str]) -> tuple[dict, bool]: ...


def envelope(tool_name: str, data: object, *, degraded: bool = False) -> dict[str, object]:
    return {
        "tool": tool_name,
        "capability": TOOL_CAPABILITIES[tool_name].value,
        "status": "degraded" if degraded else "succeeded",
        "data": data,
    }


def rejected(tool_name: str, message: str, *, code: str = "MCP_TOOL_REJECTED") -> dict[str, object]:
    return {
        "tool": tool_name,
        "capability": TOOL_CAPABILITIES[tool_name].value,
        "status": "rejected",
        "data": {},
        "error": {"code": code, "message": message, "retryable": False},
    }


def create_mcp(repository: BrandToolStore, *, require_trusted_scope: bool = True) -> FastMCP:
    def authorize(workspace_id: str, actor_id: str | None = None, task_id: str | None = None) -> None:
        if require_trusted_scope:
            require_scope().authorize(workspace_id, actor_id, task_id)

    @asynccontextmanager
    async def lifespan(_server):
        open_method = getattr(repository, "open", None)
        close_method = getattr(repository, "close", None)
        if open_method is not None:
            await open_method()
        try:
            yield {}
        finally:
            if close_method is not None:
                await close_method()

    mcp = FastMCP(
        "brandflow-brand-tools",
        instructions="Versioned BrandFlow tools. Never return hidden reasoning or secrets.",
        host="0.0.0.0",
        port=8100,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        lifespan=lifespan,
    )

    @mcp.tool(description="Search active brand documents in one workspace.", structured_output=True)
    async def search_brand_documents(workspace_id: str, query: str, limit: int = 10) -> dict[str, object]:
        authorize(workspace_id)
        return envelope("search_brand_documents", {"items": await repository.search_documents(workspace_id, query, min(max(limit, 1), 50))})

    @mcp.tool(description="Get current authoritative product facts.", structured_output=True)
    async def get_product_facts(workspace_id: str, product_id: str) -> dict[str, object]:
        authorize(workspace_id)
        facts = await repository.product_facts(workspace_id, product_id)
        return envelope("get_product_facts", {"items": facts, "authoritative": bool(facts)})

    @mcp.tool(description="Get the active brand guideline version.", structured_output=True)
    async def get_brand_guidelines(workspace_id: str, brand_id: str) -> dict[str, object]:
        authorize(workspace_id)
        guideline = await repository.brand_guidelines(workspace_id, brand_id)
        return envelope("get_brand_guidelines", guideline or {}, degraded=guideline is None)

    @mcp.tool(description="Get the active specification for a supported channel.", structured_output=True)
    async def get_channel_spec(workspace_id: str, channel: str) -> dict[str, object]:
        authorize(workspace_id)
        if channel not in CHANNELS:
            raise ToolRejected("Unsupported channel")
        specification = await repository.channel_spec(workspace_id, channel)
        return envelope("get_channel_spec", specification or {}, degraded=specification is None)

    @mcp.tool(description="Validate marketing claims against authoritative product facts.", structured_output=True)
    async def validate_marketing_claims(workspace_id: str, product_id: str, claims: list[str]) -> dict[str, object]:
        authorize(workspace_id)
        if not claims:
            return envelope("validate_marketing_claims", {"results": [], "passed": False, "issues": ["claims_required"], "validation_mode": "deterministic_exact_match"}, degraded=True)
        facts = await repository.product_facts(workspace_id, product_id)
        fact_text = " ".join(str(item.get("fact_content", "")) for item in facts).casefold()
        results = [
            {"claim": claim, "supported": claim.casefold() in fact_text, "reason": "matched_authoritative_fact" if claim.casefold() in fact_text else "authoritative_support_missing"}
            for claim in claims
        ]
        return envelope("validate_marketing_claims", {"results": results, "passed": all(item["supported"] for item in results), "validation_mode": "deterministic_exact_match"}, degraded=True)

    @mcp.tool(description="Validate channel content against the active channel specification.", structured_output=True)
    async def validate_channel_content(workspace_id: str, channel: str, content: str) -> dict[str, object]:
        authorize(workspace_id)
        if channel not in CHANNELS:
            raise ToolRejected("Unsupported channel")
        specification = await repository.channel_spec(workspace_id, channel)
        if specification is None:
            return envelope("validate_channel_content", {"passed": False, "issues": ["active_channel_spec_missing"]}, degraded=True)
        length_rules = specification.get("length_rules") or {}
        maximum = length_rules.get("max") or length_rules.get("max_characters")
        forbidden_patterns = specification.get("forbidden_patterns") or []
        issues = []
        if isinstance(maximum, int) and len(content) > maximum:
            issues.append("content_too_long")
        issues.extend(f"forbidden_pattern:{pattern}" for pattern in forbidden_patterns if str(pattern).casefold() in content.casefold())
        return envelope("validate_channel_content", {"passed": not issues, "issues": issues, "length": len(content), "spec_version": specification["version"]})

    @mcp.tool(description="Save an immutable non-approved content version.", structured_output=True)
    async def save_content_version(
        workspace_id: str,
        task_id: str,
        content_type: str,
        content: str,
        actor_id: str,
        idempotency_key: str,
        parent_version_id: str | None = None,
        channel: str | None = None,
        master_content_version_id: str | None = None,
    ) -> dict[str, object]:
        authorize(workspace_id, actor_id, task_id)
        try:
            if content_type not in {"master_draft", "master_revised", "channel_draft", "channel_revised"}:
                raise ToolRejected("Unsupported writable content type")
            if content_type.startswith("channel_") and (channel not in CHANNELS or not master_content_version_id):
                raise ToolRejected("Channel versions require a supported channel and canonical master version")
            if content_type.startswith("master_") and (channel is not None or master_content_version_id is not None):
                raise ToolRejected("Master versions cannot declare a channel lineage target")
            saved, replayed = await repository.save_version(
                workspace_id, task_id, content_type, content, parent_version_id,
                actor_id, idempotency_key, channel, master_content_version_id,
            )
        except ToolRejected as error:
            return rejected("save_content_version", str(error))
        return envelope("save_content_version", {**saved, "idempotency_replayed": replayed})

    @mcp.tool(description="Build an approved content package after persisted high-risk authorization.", structured_output=True)
    async def export_content_package(
        workspace_id: str,
        task_id: str,
        actor_id: str,
        decision_id: str,
        target_snapshot_hash: str,
        idempotency_key: str,
        formats: list[str],
    ) -> dict[str, object]:
        authorize(workspace_id, actor_id, task_id)
        try:
            result, replayed = await repository.authorized_package(
                workspace_id=workspace_id, task_id=task_id, actor_id=actor_id,
                decision_id=decision_id, target_snapshot_hash=target_snapshot_hash,
                idempotency_key=idempotency_key, action="mcp_export",
                allowed_types=("export", "final_package"), formats=formats,
            )
        except ToolRejected as error:
            return rejected("export_content_package", str(error), code="MCP_APPROVAL_INVALID")
        return envelope("export_content_package", {**result, "idempotency_replayed": replayed})

    @mcp.tool(description="Create an internal publication preview after persisted authorization.", structured_output=True)
    async def create_publish_preview(
        workspace_id: str,
        task_id: str,
        actor_id: str,
        decision_id: str,
        target_snapshot_hash: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        authorize(workspace_id, actor_id, task_id)
        try:
            result, replayed = await repository.authorized_package(
                workspace_id=workspace_id, task_id=task_id, actor_id=actor_id,
                decision_id=decision_id, target_snapshot_hash=target_snapshot_hash,
                idempotency_key=idempotency_key, action="mcp_preview",
                allowed_types=("preview", "final_package"), formats=["preview"],
            )
        except ToolRejected as error:
            return rejected("create_publish_preview", str(error), code="MCP_APPROVAL_INVALID")
        result = {"preview_id": f"preview-{target_snapshot_hash[:16]}", **result, "published": False}
        return envelope("create_publish_preview", {**result, "idempotency_replayed": replayed})

    return mcp
