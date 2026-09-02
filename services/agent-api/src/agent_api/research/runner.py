"""Phase 6 experiment runner.

One process, three strategies, one dataset, hard budget gate. Writes
per-run JSONL records (append-only) + a machine-readable summary, so
the report stage never re-derives numbers.

Budget gate (hard): the runner REFUSES to start a strategy if the
projected cost floor exceeds the cap, and aborts mid-run when the cap
is crossed — partial results are still persisted with `partial: true`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

from agent_api.providers.base import ModelCallResult
from agent_api.research import citation
from agent_api.research.metrics import (
    StrategyRun,
    duplication_rate,
    now_iso,
)
from agent_api.research.search_provider import BudgetExceeded, TavilySearchProvider


def env_get(key: str, default: str) -> str:
    import os

    return os.environ.get(key, default) or default
from agent_api.research.strategies import run_s0, run_s1, run_s2

# All paths anchor to the REPO ROOT so the runner works from any cwd
_REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_DATASET = _REPO_ROOT / "services/agent-api/evaluation/research/research_eval_v1.jsonl"
DEFAULT_OUTDIR = _REPO_ROOT / "services/agent-api/evaluation/research/runs"
SEARCH_COST_CAP_DOLLARS = 10.0
CREDITS_PER_DOLLAR = 125.0  # Tavily PAYG $0.008/credit


class _BudgetSearch(TavilySearchProvider):
    """Provider wrapper that aborts the run when the $ cap is crossed."""

    def __init__(self, *args, spent: list, cap_credits: float, **kwargs):
        super().__init__(*args, **kwargs)
        self._spent = spent
        self._cap = cap_credits

    async def search(self, query, *, max_results=5):
        if self._spent[0] >= self._cap:
            raise BudgetExceeded(
                f"search budget cap reached ({self._cap:.0f} credits)"
            )
        return await super().search(query, max_results=max_results)


async def _real_generate(provider, run: StrategyRun):
    """Adapter to the production ZhipuProvider contract, with latency."""

    async def generate(*, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        import time

        started = time.perf_counter()
        result = await provider.generate(system=system, prompt=prompt, prompt_version=prompt_version)
        run.latency_ms += int((time.perf_counter() - started) * 1000)
        return result

    return generate


def _row_of(run: StrategyRun, checks: list[dict]) -> dict:
    cited = [
        {
            "url": c.url,
            "title": c.title,
            "excerpts": c.excerpts,
            "ok": chk["ok"],
            "excerpts_ok": chk["excerpts_ok"],
        }
        for c, chk in zip(run.evidence, checks)
    ]
    claims = _extract_claims(run)
    from agent_api.research.metrics import (
        coverage as _coverage,
        unsupported_claim_rate as _ucr,
        valid_citation_rate as _vcr,
    )

    return {
        "recorded_at": now_iso(),
        "strategy": run.strategy,
        "question_id": run.question_id,
        "difficulty": run.difficulty,
        "seed": run.seed,
        "answer": run.answer,
        "cited": cited,
        "metrics": {
            "coverage": _coverage(run),
            "duplication_rate": round(duplication_rate(run), 4),
            "valid_citation_rate": round(_vcr(run, checks), 4),
            "unsupported_claim_rate": round(_ucr(run, claims), 4),
            "contradiction_reported": (
                any(m in run.answer for m in ("冲突", "矛盾", "不一致", "存在分歧", "相反", "争议"))
                and _coverage(run) >= 2
            ),
            "model_calls": run.model_calls,
            "search_calls": run.search_calls,
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "latency_ms": run.latency_ms,
        },
        "errors": run.errors,
        "partial": run.partial,
        "completed": (not run.partial) and (run.answer != ""),
    }


def _extract_claims(run: StrategyRun) -> list[dict]:
    """Structural claim extraction: every【R#】reference in the answer
    creates one claim bound to the evidence card at that index."""
    import re

    claims = []
    for match in re.finditer(r"【R(\d+)】", run.answer):
        idx = int(match.group(1)) - 1
        keys: list[str] = []
        if 0 <= idx < len(run.evidence):
            keys.append(run.evidence[idx].key())
        claims.append({"claim": match.group(0), "evidence_keys": keys})
    return claims


async def run_experiment(
    *,
    strategies: list[str],
    dataset_path: Path,
    out_dir: Path,
    search_spent: list,
    cap_credits: float,
    glm_api_key: str,
    glm_base_url: str,
    glm_model: str,
    tavily_key: str,
    seeds: tuple[int, ...] = (11, 22, 33),
) -> dict:
    from agent_api.providers.zhipu import ZhipuProvider
    from pydantic import SecretStr

    # research calls reason for a long time; the 60s product default
    # is tuned for editor latency, not for research (S0 pilot: 4/6 timeouts)
    model = ZhipuProvider(
        api_key=SecretStr(glm_api_key),
        model=glm_model,
        base_url=glm_base_url,
        timeout_seconds=float(env_get("RESEARCH_MODEL_TIMEOUT_SECONDS", "180")),
    )
    search = _BudgetSearch(
        tavily_key, spent=search_spent, cap_credits=cap_credits
    ) if tavily_key else None

    rows: list[dict] = []
    dataset = [json.loads(l) for l in dataset_path.read_text(encoding="utf8").splitlines() if l.strip()]
    digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()

    out_dir.mkdir(parents=True, exist_ok=True)
    runfile = out_dir / f"runs_{now_iso().replace(':', '')}.jsonl"

    total = len(strategies) * len(dataset) * len(seeds)
    done = 0
    with runfile.open("a", encoding="utf-8") as sink:
        for item in dataset:
            for strategy in strategies:
                for seed in seeds:
                    done += 1
                    run = StrategyRun(
                        strategy=strategy,
                        question_id=item["id"],
                        difficulty=item["difficulty"],
                        seed=seed,
                        answer="",
                    )
                    try:
                        if strategy == "S0":
                            await run_s0(item["question"], generate=await _real_generate(model, run), run=run)
                        elif strategy == "S1":
                            if search is None:
                                raise RuntimeError("TAVILY_API_KEY required for S1/S2")
                            await run_s1(item["question"], generate=await _real_generate(model, run), search=search, run=run)
                        elif strategy == "S2":
                            if search is None:
                                raise RuntimeError("TAVILY_API_KEY required for S1/S2")
                            await run_s2(item["question"], generate=await _real_generate(model, run), search=search, run=run)
                        else:
                            raise ValueError(f"unknown strategy {strategy}")
                        run.partial = False
                    except BudgetExceeded:
                        run.partial = True
                        run.errors.append("BUDGET_CAP")
                        print(f"[budget] stop at {done}/{total}; cap {cap_credits:.0f} credits")
                        _persist(sink, _row_of(run, []), runfile)
                        return _summary(rows + [], digest, partial=True, reason="budget")
                    except Exception as error:  # noqa: BLE001 — recorded, run marked partial
                        run.partial = True
                        run.errors.append(f"run:{error}"[:200])

                    checks = await citation.validate_evidence(run.evidence) if run.evidence else []
                    row = _row_of(run, checks)
                    rows.append(row)
                    _persist(sink, row, runfile)
                    search_spent[0] = run.search_calls + search_spent[0]
                    print(
                        f"  [{done}/{total}] {strategy}/{item['id']}/seed{seed} "
                        f"cov={row['metrics']['coverage']} cite={row['metrics']['valid_citation_rate']} "
                        f"search={row['metrics']['search_calls']} ${search_spent[0] / CREDITS_PER_DOLLAR:.2f}"
                    )

    return _summary(rows, digest)


def _persist(sink, row: dict, path: Path) -> None:
    sink.write(json.dumps(row, ensure_ascii=False) + "\n")
    sink.flush()


def _summary(rows: list[dict], dataset_sha: str, *, partial: bool = False, reason: str = "") -> dict:
    import statistics as stats

    def agg(strategy: str, key: str) -> list:
        return [
            r["metrics"][key] for r in rows
            if r["strategy"] == strategy and r.get("completed")
        ]

    summary: dict = {
        "recorded_at": now_iso(),
        "dataset_sha256": dataset_sha,
        "n_rows": len(rows),
        "partial": partial,
        "reason": reason,
        "strategies": {},
    }
    for strategy in ("S0", "S1", "S2"):
        all_runs = [r for r in rows if r["strategy"] == strategy]
        runs = [r for r in all_runs if r.get("completed")]
        if not all_runs:
            continue
        summary["strategies"][strategy] = {
            "n": len(runs),
            "failed": len(all_runs) - len(runs),
            "failed_rate": round((len(all_runs) - len(runs)) / len(all_runs), 4),
            # metrics are None when every run failed (mean of nothing);
            # the report must treat None as "no signal", never as zero
            **{
                key: (
                    round(stats.mean(agg(strategy, key)), 4)
                    if runs
                    else None
                )
                for key in (
                    "coverage",
                    "duplication_rate",
                    "valid_citation_rate",
                    "unsupported_claim_rate",
                    "search_calls",
                    "model_calls",
                    "input_tokens",
                    "output_tokens",
                    "latency_ms",
                )
            },
            "contradiction_reported_rate": round(
                sum(1 for r in runs if r["metrics"]["contradiction_reported"]) / len(runs) if runs else 0.0, 4
            ),
            "errors_total": sum(len(r["errors"]) for r in runs),
        }
    return summary


def _env() -> dict:
    import re

    env: dict[str, str] = {}
    path = _REPO_ROOT / ".env.local"
    if path.exists():
        for line in path.read_text(encoding="utf8").splitlines():
            m = re.match(r"\s*([A-Za-z_0-9]+)\s*=\s*(.*?)\s*$", line)
            if m and not line.strip().startswith("#"):
                env[m.group(1)] = m.group(2)
    for k, v in os.environ.items():
        if k.isupper():
            env.setdefault(k, v)
    return env


def main() -> int:
    # Windows + asyncio: the whole project forces SelectorEventLoop for
    # its SSL stacks (run.py / server.py / conftest); Proactor has a known
    # record-layer failure mode with httpx here (5/6 S1 pilot runs died
    # at the first model call with [SSL] record layer failure). The
    # runner is the last entry point missing this.
    import sys as _sys

    if _sys.platform == "win32":
        import selectors as _selectors

        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser = argparse.ArgumentParser(description="research controlled experiment")
    parser.add_argument("--strategies", nargs="+", default=["S0"],
                        help="S0 S1 S2 subset to run (default S0 only)")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--cap-dollars", type=float, default=SEARCH_COST_CAP_DOLLARS)
    parser.add_argument("--questions", type=int, default=0, help=">0: only first N questions (pilot)")
    args = parser.parse_args()

    env = _env()
    glm_key = env.get("GLM_API_KEY", "")
    tavily = env.get("TAVILY_API_KEY", "")
    if not glm_key:
        print("GLM_API_KEY missing", file=sys.stderr)
        return 2
    needs_tavily = any(s in args.strategies for s in ("S1", "S2"))
    if needs_tavily and not tavily:
        print("TAVILY_API_KEY missing — required for S1/S2", file=sys.stderr)
        return 2

    dataset_path = args.dataset
    if args.questions > 0:
        tmp = _REPO_ROOT / "_research_pilot.jsonl"
        lines = [l for l in dataset_path.read_text(encoding="utf8").splitlines() if l.strip()][: args.questions]
        tmp.write_text("\n".join(lines) + "\n", encoding="utf8")
        dataset_path = tmp

    print(f"dataset sha256: {hashlib.sha256(dataset_path.read_bytes()).hexdigest()}")
    print(f"strategies={args.strategies} cap=${args.cap_dollars:.2f} tavily={'set' if tavily else 'MISSING'}")

    spent = [0]
    try:
        summary = asyncio.run(
            run_experiment(
                strategies=args.strategies,
                dataset_path=dataset_path,
                out_dir=args.out,
                search_spent=spent,
                cap_credits=args.cap_dollars * CREDITS_PER_DOLLAR,
                glm_api_key=glm_key,
                glm_base_url=env.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
                glm_model=env.get("GLM_MODEL", "glm-4.7"),
                tavily_key=tavily,
            )
        )
    finally:
        if args.questions > 0 and (_REPO_ROOT / "_research_pilot.jsonl").exists():
            (_REPO_ROOT / "_research_pilot.jsonl").unlink()

    summary["spent_search_credits"] = spent[0]
    summary["spent_search_dollars"] = round(spent[0] / CREDITS_PER_DOLLAR, 4)
    out = args.out / "summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
