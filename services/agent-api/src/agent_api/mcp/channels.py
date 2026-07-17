from __future__ import annotations

import asyncio

from .client import RealMCPClient


class MCPChannelValidator:
    def __init__(self, client: RealMCPClient) -> None:
        self._client = client

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
