from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Protocol


class EvaluationStore(Protocol):
    async def measurement_rows(self, workspace_id: str) -> dict[str, list[dict]]: ...
    async def persist_run(self, workspace_id: str, metrics: list[dict], bad_cases: list[dict]) -> str: ...
    async def load_run(self, workspace_id: str, run_id: str) -> dict: ...


class EvaluationService:
    def __init__(self, store: EvaluationStore) -> None:
        self._store = store

    async def run(self, workspace_id: str) -> dict:
        rows = await self._store.measurement_rows(workspace_id)
        metrics = self._metrics(rows)
        bad_cases = self._bad_cases(rows)
        run_id = await self._store.persist_run(workspace_id, metrics, bad_cases)
        return {"evaluation_run_id": run_id, "metrics": metrics, "bad_case_count": len(bad_cases), "generated_at": datetime.now(UTC).isoformat()}

    def _metrics(self, rows: dict[str, list[dict]]) -> list[dict]:
        reviews = rows.get("reviews", [])
        tasks = rows.get("tasks", [])
        tools = rows.get("tools", [])
        models = rows.get("models", [])
        versions = rows.get("versions", [])
        master = [row for row in reviews if row.get("content_type", "").startswith("master_")]
        channels = [row for row in reviews if row.get("content_type", "").startswith("channel_")]
        known_costs = [float(row["estimated_cost"]) for row in models if row.get("estimated_cost") is not None]
        latencies = sorted(int(row["latency_ms"]) for row in [*tools, *models] if row.get("latency_ms") is not None)
        return [
            self._ratio("master", "review_pass_rate", sum(bool(row.get("passed")) for row in master), len(master)),
            self._ratio("channel", "review_pass_rate", sum(bool(row.get("passed")) for row in channels), len(channels)),
            self._ratio("workflow", "success_rate", sum(row.get("status") == "completed" for row in tasks), len(tasks)),
            self._ratio("mcp", "reliability", sum(row.get("output_status") == "succeeded" for row in tools), len(tools)),
            self._ratio("human_edit", "version_share", sum(row.get("created_by_type") == "human" for row in versions), len(versions)),
            {"category": "cost", "name": "estimated_total", "value": sum(known_costs) if known_costs else None, "numerator": None, "denominator": len(models), "unit": "provider_currency", "measurement_status": "measured" if models and len(known_costs) == len(models) else "partial" if known_costs else "unavailable"},
            {"category": "latency", "name": "p50_ms", "value": latencies[len(latencies) // 2] if latencies else None, "numerator": None, "denominator": len(latencies), "unit": "ms", "measurement_status": "measured" if latencies else "unavailable"},
        ]

    def _ratio(self, category: str, name: str, numerator: int, denominator: int) -> dict:
        return {"category": category, "name": name, "value": numerator / denominator if denominator else None, "numerator": numerator, "denominator": denominator, "unit": "ratio", "measurement_status": "measured" if denominator else "unavailable"}

    def _bad_cases(self, rows: dict[str, list[dict]]) -> list[dict]:
        cases = []
        for row in rows.get("reviews", []):
            if not row.get("passed"):
                cases.append({"task_id": row.get("task_id"), "category": row.get("review_type", "review_failure"), "severity": row.get("max_severity") or "warning", "summary": "Review did not pass", "reproducible": True})
        for row in rows.get("tools", []):
            if row.get("output_status") != "succeeded":
                cases.append({"task_id": row.get("task_id"), "category": "mcp_failure", "severity": "critical" if row.get("capability") == "high_risk" else "warning", "summary": row.get("error_code") or "Tool call failed", "reproducible": True})
        return cases

    async def report(self, workspace_id: str, run_id: str, format: str) -> tuple[str, str]:
        run = await self._store.load_run(workspace_id, run_id)
        if format == "json":
            return "application/json", json.dumps(run, ensure_ascii=False, default=str, sort_keys=True)
        if format == "csv":
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=["category", "name", "value", "numerator", "denominator", "unit", "measurement_status"])
            writer.writeheader()
            writer.writerows(run["metrics"])
            return "text/csv", output.getvalue()
        if format == "markdown":
            lines = [f"# BrandFlow evaluation {run_id}", "", "| Category | Metric | Value | Measurement |", "|---|---|---:|---|"]
            for metric in run["metrics"]:
                value = "unavailable" if metric["value"] is None else str(metric["value"])
                lines.append(f"| {metric['category']} | {metric['name']} | {value} | {metric['measurement_status']} |")
            return "text/markdown", "\n".join(lines) + "\n"
        raise ValueError("Unsupported report format")
