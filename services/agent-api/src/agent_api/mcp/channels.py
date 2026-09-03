from __future__ import annotations

import asyncio

from .client import RealMCPClient

# The C-end product surface is three built-in preview tabs; the MCP spec
# table may extend it per workspace (agentization P2-3). This tuple is the
# FALLBACK when the MCP service is unreachable - channel listing is a
# product feature, not a security boundary, so a degraded answer (the
# built-ins) beats an unavailable one.
FALLBACK_CONSUMER_CHANNELS = ("wechat_website", "xiaohongshu", "video_script_60s")


class MCPChannelValidator:
    def __init__(self, client: RealMCPClient) -> None:
        self._client = client

    async def supported_consumer_channels(self, *, workspace_id: str) -> tuple[str, ...]:
        """Workspace-usable channels for the C-end: built-in previews plus
        any custom channel that has an active spec row (P2-3). Falls back
        to the built-ins when the MCP service is unavailable."""
        try:
            client = self._client.for_task(
                workspace_id=workspace_id,
                task_id="discovery",
                workflow_node="list_channels",
            )
            result = await client.call("supported_channels", {"workspace_id": workspace_id})
            channels = [str(channel) for channel in result.get("data", {}).get("channels", [])]
            if channels:
                return tuple(channels)
        except Exception:  # noqa: BLE001 — degraded listing, see fallback note
            pass
        return FALLBACK_CONSUMER_CHANNELS

    async def validate(
        self, *, workspace_id: str, task_id: str, product_id: str,
        channel: str, content: str, claims: list[str],
    ) -> dict[str, dict]:
        client = self._client.for_task(
            workspace_id=workspace_id,
            task_id=task_id,
            workflow_node=f"review_channel:{channel}",
        )
        format_result, fact_result = await asyncio.gather(
            client.call("validate_channel_content", {
                "workspace_id": workspace_id, "channel": channel, "content": content,
            }),
            client.call("validate_marketing_claims", {
                "workspace_id": workspace_id, "product_id": product_id, "claims": claims,
            }),
        )
        format_data = format_result.get("data", {})
        fact_data = fact_result.get("data", {})
        unsupported = [
            str(item.get("claim")) for item in fact_data.get("results", [])
            if not item.get("supported")
        ]
        format_issues = [str(issue) for issue in format_data.get("issues", [])]
        return {
            "format": {"passed": bool(format_data.get("passed")), "issues": format_issues},
            "facts": {"passed": bool(fact_data.get("passed")), "issues": [f"unsupported_new_claim:{claim}" for claim in unsupported] or [str(issue) for issue in fact_data.get("issues", [])]},
            "brand": {"passed": not any(issue.startswith("forbidden_pattern:") for issue in format_issues), "issues": [issue for issue in format_issues if issue.startswith("forbidden_pattern:")]},
            "compliance": {"passed": not unsupported, "issues": [f"unverified_claim:{claim}" for claim in unsupported]},
        }
