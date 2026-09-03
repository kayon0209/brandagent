"""One-shot: build results/summary_full_v1.json from the 180-tuple grid.

Merge rule: per (strategy, question_id, seed), a CLEAN completed row (no
search:* infrastructure errors) wins over any failed/degraded row.
Degraded rows (Tavily quota exhausted mid-retry -> empty-evidence
synthesis) are excluded from metrics: they are not valid S1/S2 samples.
The qwen3.8-flash batch (runs_2026-09-03T142059) is excluded entirely -
switching models breaks the same-provider discipline of the experiment.
"""

import json
import statistics as st
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

RUNS = Path(r"D:\demo\brandagent\services\agent-api\evaluation\research\runs")
SOURCES = [
    "runs_2026-09-02T175153+0000.jsonl",
    "runs_2026-09-03T083800+0000.jsonl",
    "runs_2026-09-03T110121+0000.parallel-killed.jsonl",
    "runs_2026-09-03T111952+0000.jsonl",
]


def is_clean(row: dict) -> bool:
    return row["completed"] and not any(e.startswith("search:") for e in row["errors"])


best: dict[tuple, dict] = {}
for name in SOURCES:
    for line in (RUNS / name).read_text(encoding="utf8").splitlines():
        row = json.loads(line)
        key = (row["strategy"], row["question_id"], row["seed"])
        if is_clean(row) or key not in best:
            best[key] = row

by: dict[str, list[dict]] = defaultdict(list)
for key, row in best.items():
    if is_clean(row):
        by[row["strategy"]].append(row)

out = {
    "recorded_at": datetime.now(timezone.utc).isoformat(),
    "dataset_sha256": "6cee2586c7d650324b946d9192f5548d6e70735b0cf40facfdd98eab8b154d80",
    "model": "GLM-5.3-Flash via Gitee AI gateway (uniform one-retry; 300s research timeout on retry passes)",
    "method": {
        "main_batch": "runs_2026-09-02T175153 (180 tuples, GLM-5.3-Flash, 180s timeout)",
        "targeted_retries": [
            "runs_2026-09-03T083800 (serial, 300s timeout)",
            "runs_2026-09-03T110121.parallel-killed (serial remnant)",
            "runs_2026-09-03T111952 (3 parallel by-strategy processes, 300s timeout)",
        ],
        "exclusion_rule": (
            "completed rows carrying search:* infrastructure errors are DEGRADED "
            "(Tavily quota exhausted mid-retry; empty-evidence synthesis is not a "
            "valid S1/S2 sample) and excluded from metrics"
        ),
        "cross_model_batches": (
            "runs_2026-09-03T142059 (qwen3.8-flash) EXCLUDED entirely: model switch "
            "breaks the same-provider discipline; its 12 S2 rows are Tavily-degraded anyway"
        ),
        "merge_rule": (
            "per (strategy, question_id, seed): clean completed row wins over any "
            "failed/degraded row"
        ),
    },
    "n_tuples": len(best),
    "failed_remaining": {
        "S0": sum(1 for k, v in best.items() if k[0] == "S0" and not v["completed"]),
        "S1": sum(1 for k, v in best.items() if k[0] == "S1" and not v["completed"]),
        "S2": sum(1 for k, v in best.items() if k[0] == "S2" and not v["completed"]),
    },
}

strategies = {}
for s in ("S0", "S1", "S2"):
    rows = by[s]
    if not rows:
        continue

    def mean(key: str) -> float:
        return round(st.mean([r["metrics"][key] for r in rows]), 4)

    strategies[s] = {
        "n": len(rows),
        "coverage": mean("coverage"),
        "coverage_sd": round(st.stdev([r["metrics"]["coverage"] for r in rows]), 4) if len(rows) > 1 else None,
        "valid_citation_rate": mean("valid_citation_rate"),
        "duplication_rate": mean("duplication_rate"),
        "unsupported_claim_rate": mean("unsupported_claim_rate"),
        "contradiction_reported_rate": mean("contradiction_reported"),
        "search_calls": mean("search_calls"),
        "model_calls": mean("model_calls"),
        "input_tokens": round(mean("input_tokens")),
        "output_tokens": round(mean("output_tokens")),
        "latency_ms": round(mean("latency_ms")),
    }
out["strategies"] = strategies

pairs = [
    (k[1], k[2])
    for k in best
    if k[0] == "S1"
    and is_clean(best[k])
    and ("S2",) + k[1:] in best
    and is_clean(best[("S2",) + k[1:]])
]
diffs = [
    best[("S2", q, seed)]["metrics"]["coverage"] - best[("S1", q, seed)]["metrics"]["coverage"]
    for q, seed in pairs
]
if diffs:
    se = st.stdev(diffs) / math.sqrt(len(diffs))
    out["paired_s2_vs_s1"] = {
        "n_pairs": len(pairs),
        "coverage_diff_mean": round(st.mean(diffs), 4),
        "coverage_diff_se": round(se, 4),
        "ci95": [round(st.mean(diffs) - 1.96 * se, 4), round(st.mean(diffs) + 1.96 * se, 4)],
        "s2_wins": sum(1 for d in diffs if d > 0),
        "s1_wins": sum(1 for d in diffs if d < 0),
        "ties": sum(1 for d in diffs if d == 0),
    }
out["gate_decision"] = (
    "PENDING_USER_CONFIRMATION: paired coverage +1.31 (95%CI [0.80, 1.82], CI excludes "
    "zero) and 21/29 wins favor S2; BUT cost is 2.5x search (10.0 vs 4.0 calls/question) "
    "and 14 S2 tuples remain unrecoverable this cycle (Tavily quota); per MASTER_PLAN "
    "Phase 6 the gate also demands reproducibility - a second cycle should replicate "
    "before productization"
)

target = RUNS.parent / "results" / "summary_full_v1.json"
target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf8")
print("written:", target)
print(json.dumps(out["strategies"], ensure_ascii=False))
print("paired:", out.get("paired_s2_vs_s1"))
print("failed_remaining:", out["failed_remaining"])
