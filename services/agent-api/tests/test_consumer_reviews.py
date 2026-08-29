"""Consumer review mapper (upgrade plan task 11).

The mapper translates machine review dimensions (factual, citation,
brand, channel_format, compliance) into a small set of spoken-language
templates. Blocking is reserved for unsupported factual claims, explicit
compliance violations, and export-snapshot mismatches — never B-end
workflow jargon.
"""

from __future__ import annotations

import pytest

from agent_api.application.consumer_reviews import ConsumerReviewMapper


def review(dimension: str, passed: bool, *, severity: str = "warning", message: str = "") -> dict:
    return {"dimension": dimension, "passed": passed, "severity": severity, "message": message}


def mapper() -> ConsumerReviewMapper:
    return ConsumerReviewMapper()


def test_passing_reviews_map_to_no_bubbles() -> None:
    bubbles = mapper().map_bubbles(
        reviews=[review("factual", True), review("citation", True), review("channel_format", True)],
        master_snapshot_hash="h" * 64,
        export_snapshot_hash="h" * 64,
    )
    assert bubbles == []


def test_machine_dimensions_map_to_spoken_templates_not_jargon() -> None:
    bubbles = mapper().map_bubbles(
        reviews=[
            review("factual", False, severity="critical", message="fact X unsupported"),
            review("channel_format", False, severity="warning", message="too long"),
        ],
        master_snapshot_hash="h" * 64,
        export_snapshot_hash="h" * 64,
    )
    assert len(bubbles) == 2
    texts = [bubble["text"] for bubble in bubbles]
    joined = "".join(texts)
    # spoken templates, no B-end workflow vocabulary
    for banned in ("事实与主张一致", "谱系", "审批", "lineage", "渠道格式", "compliance"):
        assert banned not in joined
    # every bubble is human-readable and actionable
    for bubble in bubbles:
        assert bubble["text"]
        assert bubble["kind"] in ("needs_fix", "blocking", "hint")


def test_unsupported_factual_claim_is_blocking() -> None:
    bubbles = mapper().map_bubbles(
        reviews=[review("factual", False, severity="critical", message="claim without source")],
        master_snapshot_hash="h" * 64,
        export_snapshot_hash="h" * 64,
    )
    assert bubbles[0]["kind"] == "blocking"
    assert "来源" in bubbles[0]["text"]


def test_explicit_compliance_violation_is_blocking() -> None:
    bubbles = mapper().map_bubbles(
        reviews=[review("compliance", False, severity="critical", message="absolute claim")],
        master_snapshot_hash="h" * 64,
        export_snapshot_hash="h" * 64,
    )
    assert bubbles[0]["kind"] == "blocking"


def test_export_snapshot_mismatch_is_blocking() -> None:
    bubbles = mapper().map_bubbles(
        reviews=[],
        master_snapshot_hash="a" * 64,
        export_snapshot_hash="b" * 64,
    )
    assert len(bubbles) == 1
    assert bubbles[0]["kind"] == "blocking"
    assert "采用了最新版" in bubbles[0]["text"] or "重新生成" in bubbles[0]["text"]


def test_warning_level_issues_are_never_blocking() -> None:
    bubbles = mapper().map_bubbles(
        reviews=[
            review("channel_format", False, severity="warning", message="length"),
            review("brand", False, severity="warning", message="tone"),
        ],
        master_snapshot_hash="h" * 64,
        export_snapshot_hash="h" * 64,
    )
    assert all(bubble["kind"] != "blocking" for bubble in bubbles)


def test_empty_reviews_with_matching_snapshots_render_no_false_all_clear() -> None:
    # Task 12 requirement: review empty must not fabricate "全部通过"
    summary = mapper().summarize([], master_snapshot_hash="h" * 64, export_snapshot_hash="h" * 64)
    assert summary["empty"] is True
    assert "全部通过" not in summary["headline"]
    assert "暂未发现" in summary["headline"]
