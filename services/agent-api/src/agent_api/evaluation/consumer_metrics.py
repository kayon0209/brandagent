"""Consumer golden evaluation metrics (upgrade plan task 14).

Deterministic metrics over the golden dataset consumer_golden_v1.jsonl.
Every case carries dataset_version, case_id, input, expected_constraints,
and source_excerpt_ids — never production material. Source attribution
reads the structured supportingExcerptIds field, never guessed from the
generated text.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from agent_api.evaluation.metrics import EvaluationStore  # shared protocol if needed  # noqa: F401

GOLDEN_PATH = Path(__file__).resolve().parents[3] / "evaluation" / "consumer_golden_v1.jsonl"
DATASET_VERSION = "consumer_golden_v1"

# numeric claims that require lineage (shared rule with the assist service)
_NUMERIC_CLAIM = re.compile(r"\d+%|\d+(?:\.\d+)?[万亿倍]")

GATE_THRESHOLDS = {
    "excerpt_attribution_precision": 1.0,
    "unsupported_claim_rate": 0.0,
    "core_idea_preservation": 1.0,
    "channel_format_pass_rate": 1.0,
    "shorten_compression_max": 1.0,
}


def load_golden(path: Path | None = None) -> list[dict]:
    """Load and validate the golden dataset rows."""

    target = path or GOLDEN_PATH
    cases: list[dict] = []
    with target.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            for required in ("dataset_version", "case_id", "input", "expected_constraints", "source_excerpt_ids"):
                if required not in row:
                    raise ValueError(f"golden case missing field {required}: {row}")
            cases.append(row)
    return cases


def excerpt_attribution_precision(cases: list[dict]) -> dict:
    """Supporting excerpt ids must all trace to the case's source set."""

    judged = 0
    correct = 0
    for case in cases:
        supporting = (case.get("output") or {}).get("supportingExcerptIds") or []
        if not supporting:
            continue
        judged += 1
        if set(supporting) <= set(case["source_excerpt_ids"]):
            correct += 1
    return _ratio("excerpt_attribution_precision", correct, judged)


def unsupported_claim_rate(cases: list[dict]) -> dict:
    """Numeric claims without lineage in any source excerpt count as unsupported."""

    unsupported = 0
    checked = 0
    for case in cases:
        output_text = str((case.get("output") or {}).get("content", ""))
        if not output_text:
            continue
        checked += 1
        source_text = " ".join(
            str(excerpt) for excerpt in case.get("expected_constraints", {}).get("source_texts", [])
        )
        for claim in _NUMERIC_CLAIM.findall(output_text):
            if claim not in source_text:
                unsupported += 1
                break
    return _ratio("unsupported_claim_rate", unsupported, checked)


def core_idea_preservation(cases: list[dict]) -> dict:
    """The core idea must still be represented in accepted outputs.

    A case passes when the output contains the leading fragment of the
    core idea, or (for shorten outputs that legitimately compress) the
    output is a prefix fragment of the core idea itself.
    """

    preserved = 0
    judged = 0
    for case in cases:
        if case.get("kind") not in ("suggestion", "channel"):
            continue
        idea = case["expected_constraints"].get("core_idea")
        output = (case.get("output") or {}).get("content")
        if not idea or output is None:
            continue
        judged += 1
        idea_text, output_text = str(idea), str(output)
        head = idea_text[:12]
        if head in output_text or (output_text and output_text in idea_text):
            preserved += 1
    return _ratio("core_idea_preservation", preserved, judged)


def channel_format_pass_rate(cases: list[dict]) -> dict:
    """Channel outputs must satisfy their expected structural constraints."""

    passed = 0
    judged = 0
    for case in cases:
        constraint = case["expected_constraints"].get("channel_format")
        output = (case.get("output") or {}).get("content")
        if not constraint or output is None:
            continue
        judged += 1
        if _channel_format_ok(str(constraint), str(output)):
            passed += 1
    return _ratio("channel_format_pass_rate", passed, judged)


def _channel_format_ok(constraint: str, output: str) -> bool:
    if constraint == "wechat_paragraphs":
        return len([p for p in output.split("\n") if p.strip()]) >= 2
    if constraint == "xiaohongshu_tags":
        return "#" in output
    if constraint == "video_script_lines":
        return len([l for l in output.split("\n") if l.strip()]) >= 2
    return True


def shorten_compression(cases: list[dict]) -> dict:
    """Shorten outputs must not be LONGER than their inputs."""

    compressed = 0
    judged = 0
    ratios: list[float] = []
    for case in cases:
        if case.get("kind") != "suggestion" or case["input"].get("action") != "shorten":
            continue
        output = (case.get("output") or {}).get("content")
        if output is None:
            continue
        judged += 1
        selected = str(case["input"].get("selected_text", ""))
        ratio = len(str(output)) / max(len(selected), 1)
        ratios.append(ratio)
        if ratio <= GATE_THRESHOLDS["shorten_compression_max"]:
            compressed += 1
    if not ratios:
        return {"category": "shorten", "name": "compression_pass_rate", "value": None, "numerator": 0, "denominator": 0, "unit": "ratio", "measurement_status": "unavailable"}
    return {
        "category": "shorten",
        "name": "compression_pass_rate",
        "value": compressed / judged,
        "numerator": compressed,
        "denominator": judged,
        "unit": "ratio",
        "measurement_status": "measured",
    }


def evaluate(cases: list[dict]) -> dict:
    return {
        "dataset_version": DATASET_VERSION,
        "case_count": len(cases),
        "metrics": [
            excerpt_attribution_precision(cases),
            unsupported_claim_rate(cases),
            core_idea_preservation(cases),
            channel_format_pass_rate(cases),
            shorten_compression(cases),
        ],
        "gate": gate_status(cases),
    }


def gate_status(cases: list[dict]) -> dict:
    metrics = {
        "excerpt_attribution_precision": excerpt_attribution_precision(cases)["value"],
        "unsupported_claim_rate": unsupported_claim_rate(cases)["value"],
        "core_idea_preservation": core_idea_preservation(cases)["value"],
        "channel_format_pass_rate": channel_format_pass_rate(cases)["value"],
    }
    failed = {
        name: {"value": value, "threshold": threshold}
        for name, value, threshold in [
            ("excerpt_attribution_precision", metrics["excerpt_attribution_precision"], GATE_THRESHOLDS["excerpt_attribution_precision"]),
            ("unsupported_claim_rate", metrics["unsupported_claim_rate"], GATE_THRESHOLDS["unsupported_claim_rate"]),
            ("core_idea_preservation", metrics["core_idea_preservation"], GATE_THRESHOLDS["core_idea_preservation"]),
            ("channel_format_pass_rate", metrics["channel_format_pass_rate"], GATE_THRESHOLDS["channel_format_pass_rate"]),
        ]
        if value is not None and not _gate_pass(name, value)
    }
    return {"passed": not failed, "failed": failed, "thresholds": GATE_THRESHOLDS}


def _gate_pass(name: str, value: float) -> bool:
    if name == "unsupported_claim_rate":
        return value <= GATE_THRESHOLDS["unsupported_claim_rate"]
    if name == "excerpt_attribution_precision":
        return value >= GATE_THRESHOLDS["excerpt_attribution_precision"]
    if name == "core_idea_preservation":
        return value >= GATE_THRESHOLDS["core_idea_preservation"]
    if name == "channel_format_pass_rate":
        return value >= GATE_THRESHOLDS["channel_format_pass_rate"]
    return True


def _ratio(name: str, numerator: int, denominator: int, *, category: str = "consumer") -> dict:
    return {
        "category": category,
        "name": name,
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
        "unit": "ratio",
        "measurement_status": "measured" if denominator else "unavailable",
    }
