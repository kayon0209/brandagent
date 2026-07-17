import pytest

from agent_api.evaluation.metrics import EvaluationService


class Store:
    async def measurement_rows(self, workspace_id):
        return {
            "reviews": [{"task_id": "t1", "content_type": "master_draft", "review_type": "factual", "passed": True}, {"task_id": "t2", "content_type": "channel_draft", "review_type": "brand", "passed": False, "max_severity": "critical"}],
            "tasks": [{"status": "completed"}, {"status": "failed"}],
            "tools": [{"task_id": "t1", "output_status": "succeeded", "latency_ms": 10}, {"task_id": "t2", "output_status": "failed", "latency_ms": 20, "error_code": "MCP_TIMEOUT", "capability": "read"}],
            "models": [{"latency_ms": 30, "estimated_cost": None}],
            "versions": [{"created_by_type": "model"}, {"created_by_type": "human"}],
        }
    async def persist_run(self, workspace_id, metrics, bad_cases): self.saved = {"metrics": metrics, "bad_cases": bad_cases}; return "run-1"
    async def load_run(self, workspace_id, run_id): return self.saved


@pytest.mark.asyncio
async def test_evaluation_uses_measured_rows_and_keeps_unknown_cost_nullable() -> None:
    store = Store()
    result = await EvaluationService(store).run("workspace-1")
    cost = next(metric for metric in result["metrics"] if metric["category"] == "cost")
    workflow = next(metric for metric in result["metrics"] if metric["category"] == "workflow")
    assert cost["value"] is None
    assert cost["measurement_status"] == "unavailable"
    assert workflow["value"] == 0.5
    assert next(metric for metric in result["metrics"] if metric["category"] == "human_edit")["value"] == 0.5
    assert result["bad_case_count"] == 2


@pytest.mark.asyncio
async def test_reports_json_csv_and_markdown_without_inventing_values() -> None:
    store = Store()
    service = EvaluationService(store)
    await service.run("workspace-1")
    for format in ("json", "csv", "markdown"):
        media_type, content = await service.report("workspace-1", "run-1", format)
        assert media_type
        assert content
    _, markdown = await service.report("workspace-1", "run-1", "markdown")
    assert "unavailable" in markdown
