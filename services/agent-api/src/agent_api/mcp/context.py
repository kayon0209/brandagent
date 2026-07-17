import asyncio

from agent_api.domain.models import AgentState

from .client import RealMCPClient


class MCPContextGateway:
    def __init__(self, client: RealMCPClient) -> None:
        self._client = client

    async def retrieve(self, state: AgentState) -> dict[str, object]:
        if state.brief is None or state.brief.product_id is None or state.brief.brand_id is None:
            return {"verified_fact_ids": []}
        client = self._client.for_task(workspace_id=state.workspace_id, task_id=state.task_id, workflow_node="retrieve_brand_context")
        fact_result, guideline_result = await asyncio.gather(
            client.call("get_product_facts", {"workspace_id": state.workspace_id, "product_id": state.brief.product_id}),
            client.call("get_brand_guidelines", {"workspace_id": state.workspace_id, "brand_id": state.brief.brand_id}),
        )
        specification_results = await asyncio.gather(*[
            client.call("get_channel_spec", {"workspace_id": state.workspace_id, "channel": channel.value})
            for channel in state.selected_channels
        ])
        facts = fact_result.get("data", {}).get("items", [])
        guideline = guideline_result.get("data", {})
        channel_versions = {
            result["data"]["channel"]: result["data"]["version"]
            for result in specification_results
            if result.get("status") == "succeeded" and result.get("data", {}).get("version")
        }
        return {
            "verified_fact_ids": [str(item["fact_id"]) for item in facts],
            "retrieved_source_ids": list({str(item["source_document_id"]) for item in facts}),
            "brand_guideline_version": guideline.get("version"),
            "channel_spec_versions": channel_versions,
        }
