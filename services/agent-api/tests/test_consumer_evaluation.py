"""Consumer golden evaluation tests (upgrade plan task 14).

Schema discipline + deterministic metric behavior + gate computation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_api.evaluation.consumer_metrics import (
    DATASET_VERSION,
    GATE_THRESHOLDS,
    channel_format_pass_rate,
    core_idea_preservation,
    evaluate,
    excerpt_attribution_precision,
    load_golden,
    shorten_compression,
    unsupported_claim_rate,
)


def test_golden_dataset_exists_with_planned_minimum() -> None:
    cases = load_golden()
    assert len(cases) >= 100, "planned minimum: 90 action + 10 refusal + 10 engineering"
    kinds: dict[str, int] = {}
    for case in cases:
        kinds[case["kind"]] = kinds.get(case["kind"], 0) + 1
    assert kinds.get("suggestion", 0) >= 45  # 15 x expand/replace/shorten
    assert kinds.get("channel", 0) >= 45  # 15 x wechat/xhs/video
    assert kinds.get("refusal", 0) >= 10
    assert kinds.get("engineering", 0) >= 10


def test_every_golden_row_carries_the_required_schema() -> None:
    for case in load_golden():
        for field in ("dataset_version", "case_id", "input", "expected_constraints", "source_excerpt_ids"):
            assert field in case, f"{case.get('case_id')} is missing {field}"
        assert case["dataset_version"] == DATASET_VERSION


def test_attribution_reads_structured_ids_never_guesses_from_text() -> None:
    cases = load_golden()
    metric = excerpt_attribution_precision(cases)
    assert metric["denominator"] > 0
    assert metric["value"] == 1.0, "every supporting id must trace to the case source set"


def test_unsupported_numeric_claims_count_against_the_rate() -> None:
    good = {
        "dataset_version": DATASET_VERSION,
        "case_id": "unit-good",
        "input": {"action": "expand"},
        "output": {"content": "转化率提升了 300%。"},
        "expected_constraints": {"source_texts": ["素材：转化率提升了 300%。"]},
        "source_excerpt_ids": ["ex-1"],
    }
    bad = {
        **good,
        "case_id": "unit-bad",
        "output": {"content": "转化率提升了 300%。"},
        "expected_constraints": {"source_texts": ["素材：不含数字。"]},
    }
    metric = unsupported_claim_rate([good, bad])
    assert metric["numerator"] == 1
    assert metric["value"] == 0.5


def test_shorten_outputs_must_not_grow_the_text() -> None:
    cases = load_golden()
    metric = shorten_compression(cases)
    assert metric["denominator"] == 15
    assert metric["value"] == 1.0


def test_channel_formats_are_structurally_distinct_and_pass() -> None:
    cases = load_golden()
    metric = channel_format_pass_rate(cases)
    assert metric["denominator"] == 45
    assert metric["value"] == 1.0


def test_core_idea_survives_every_accepted_output() -> None:
    cases = load_golden()
    metric = core_idea_preservation(cases)
    assert metric["denominator"] == 90  # suggestion + channel outputs
    assert metric["value"] == 1.0


def test_evaluate_reports_the_gate_against_written_thresholds() -> None:
    report = evaluate(load_golden())
    assert report["dataset_version"] == DATASET_VERSION
    assert report["gate"]["passed"] is True
    assert report["gate"]["thresholds"] == GATE_THRESHOLDS


def test_gate_fails_loudly_when_a_case_breaks() -> None:
    cases = load_golden()
    cases[0]["output"]["supportingExcerptIds"] = ["ex-foreign"]
    report = evaluate(cases)
    assert report["gate"]["passed"] is False
    assert "excerpt_attribution_precision" in report["gate"]["failed"]
