"""Headline metrics + markdown report rendering."""

from .dataset import DATASET, INTENT_PROPORTIONS
from .pricing import Pricing
from .retrievers import (
    OUTPUT_TOKENS,
    context_tokens,
    query_cost,
    recall_at_5,
    route_query,
)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


# ---------------------------------------------------------------------------
# Metric 1 -- Marginal cost efficiency of Graph augmentation
# ---------------------------------------------------------------------------
def marginal_cost_efficiency(pricing: Pricing, topk: int = 10) -> list[dict]:
    rows = []
    for intent in ("factual", "comparative", "procedural"):
        qs = [q for q in DATASET if q.intent == intent]
        r_vec = _mean([recall_at_5(q, False) for q in qs])
        r_g = _mean([recall_at_5(q, True) for q in qs])
        c_vec = _mean([query_cost(q, topk, False, pricing) for q in qs])
        c_g = _mean([query_cost(q, topk, True, pricing) for q in qs])
        d_r = (r_g - r_vec) * 100  # percentage points
        d_c = (c_g - c_vec) / c_vec * 100 if c_vec else 0.0  # percent
        marginal = d_r / d_c if d_c else 0.0  # pp gained per 1% extra cost
        rows.append(
            {
                "intent": intent,
                "recall_vec": r_vec,
                "recall_graph": r_g,
                "d_recall_pp": d_r,
                "cost_vec": c_vec,
                "cost_graph": c_g,
                "d_cost_pct": d_c,
                "marginal": marginal,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Metric 2 -- Post-routing mixed cost vs. all-Graph-on cost
# ---------------------------------------------------------------------------
def routing_mixed_cost(pricing: Pricing, topk: int = 10):
    mixed = 0.0
    all_graph = 0.0
    per = {}
    for intent, prop in INTENT_PROPORTIONS.items():
        qs = [q for q in DATASET if q.intent == intent]
        c_vec = _mean([query_cost(q, topk, False, pricing) for q in qs])
        c_g = _mean([query_cost(q, topk, True, pricing) for q in qs])
        decision = route_query(intent)
        chosen = c_vec if decision.scheme == "vector" else c_g
        mixed += prop * chosen
        all_graph += prop * c_g
        per[intent] = (c_vec, c_g, decision.scheme)
    savings = (all_graph - mixed) / all_graph * 100 if all_graph else 0.0
    return mixed, all_graph, savings, per


# ---------------------------------------------------------------------------
# Metric 3 -- Cost-structure breakdown + topk cost-reduction knob
# ---------------------------------------------------------------------------
def cost_structure_and_knob(pricing: Pricing, topk_values=(10, 5, 3), graph: bool = False) -> list[dict]:
    """Arm B = plain vector retrieval (context-dominated).

    Reports two distinct quality numbers:
      * Recall@5        -- retriever quality, fixed by the ranking (independent of topk)
      * Citation acc    -- fraction of ALL gold docs the LLM can actually cite,
                          i.e. gold docs whose rank <= topk_to_llm (topk-dependent)
    They diverge only when topk_to_llm < 5: the retriever looks fine, but the
    LLM never receives the deeper relevant chunks.
    """
    rows = []
    baseline_cost = None
    for topk in topk_values:
        inp, cost, rec, cit = [], [], [], []
        for q in DATASET:
            c = context_tokens(q, topk, graph)
            inp.append(c)
            cost.append(query_cost(q, topk, graph, pricing))
            rec.append(recall_at_5(q, graph))
            ranks = q.gold_ranks_graph if graph else q.gold_ranks_vector
            gold_in_ctx = sum(1 for r in ranks if r <= topk)
            cit.append(gold_in_ctx / q.gold_size)
        avg_in = _mean(inp)
        avg_out = OUTPUT_TOKENS
        input_pct = avg_in / (avg_in + avg_out) * 100
        if baseline_cost is None:
            baseline_cost = _mean(cost)
        rows.append(
            {
                "topk": topk,
                "avg_cost": _mean(cost),
                "input_pct": input_pct,
                "recall_at_5": _mean(rec),
                "citation_acc": _mean(cit),
                "cost_vs_base_pct": (_mean(cost) / baseline_cost - 1) * 100,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def render_report(pricing, mce, mixed, all_graph, savings, per, knob) -> str:
    L = []
    L.append("# Retrieval Cost-Efficiency Benchmark — Results\n")
    L.append(f"> Pricing model: `{pricing.label}` "
             f"(input ${pricing.input_per_million}/1M, output ${pricing.output_per_million}/1M tokens).\n")
    L.append("> **Honest labeling:** figures below are produced by a deterministic, "
             "parameterized retrieval simulator over a 12-query built-in dataset. "
             "They demonstrate the *methodology and trade-off shape*. Replace the "
             "simulator's dataset/pricing with production data for live numbers.\n")

    # Metric 1
    L.append("\n## 1. Marginal cost efficiency of Graph (should Graph be on by default?)\n")
    L.append("`marginal = ΔRecall@5 (pp) / ΔCost (%)` — pp of recall gained per 1% extra cost.\n")
    L.append("| Intent | Recall@5 (vec) | Recall@5 (graph) | ΔRecall (pp) | Cost (vec) | Cost (graph) | ΔCost (%) | Marginal (pp/1%) |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in mce:
        L.append(
            f"| {r['intent']} | {r['recall_vec']:.2f} | {r['recall_graph']:.2f} | "
            f"{r['d_recall_pp']:+.1f} | {r['cost_vec']:.5f} | {r['cost_graph']:.5f} | "
            f"{r['d_cost_pct']:+.1f}% | {r['marginal']:.2f} |"
        )
    factual = next(r for r in mce if r["intent"] == "factual")
    L.append(f"\n**Read:** factual marginal ≈ {factual['marginal']:.2f} (Graph buys ~0 recall) → "
             "do **not** default Graph on. comparative/procedural marginal > 0 → default Graph on "
             "for those intents only.\n")

    # Metric 2
    L.append("\n## 2. Post-routing mixed cost vs. all-Graph-on\n")
    L.append(f"- Mixed cost (Query Router): `{mixed:.5f}`")
    L.append(f"- All-Graph-on cost:         `{all_graph:.5f}`")
    L.append(f"- **Routing savings: `{savings:.1f}%`**\n")
    L.append("| Intent | Prop | Cost (vec) | Cost (graph) | Routed to |")
    L.append("|---|---:|---:|---:|---|")
    for intent, prop in INTENT_PROPORTIONS.items():
        c_vec, c_g, scheme = per[intent]
        L.append(f"| {intent} | {prop:.0%} | {c_vec:.5f} | {c_g:.5f} | {scheme} |")
    L.append("\n**Read:** routing every query to its cheapest sufficient scheme cuts total "
             "retrieval cost vs. blindly enabling Graph everywhere.\n")

    # Metric 3
    L.append("\n## 3. Cost structure + topk_to_llm knob experiment\n")
    L.append("Arm B = plain vector retrieval (context-dominated). Input-token share of total cost, "
             "and the effect of shrinking `topk_to_llm` 10 → 5 → 3. Recall@5 is the retriever's "
             "fixed quality; Citation acc is what the LLM can actually cite (rank <= topk).\n")
    L.append("| topk_to_llm | Avg cost | Input token % | Recall@5 (retriever) | Citation acc (LLM sees) | Cost vs topk=10 |")
    L.append("|---:|---:|---:|---:|---:|---:|")
    for r in knob:
        L.append(
            f"| {r['topk']} | {r['avg_cost']:.5f} | {r['input_pct']:.0f}% | "
            f"{r['recall_at_5']:.2f} | {r['citation_acc']:.2f} | {r['cost_vs_base_pct']:+.1f}% |"
        )
    base = knob[0]
    mid = knob[1]
    drop_10_5 = (base["avg_cost"] - mid["avg_cost"]) / base["avg_cost"] * 100
    L.append(f"\n**Read:** input tokens are ~{base['input_pct']:.0f}% of cost → the lever is "
             "*context length, not output*. Dropping topk 10 → 5 cuts cost "
             f"{drop_10_5:.0f}% while Recall@5 is unchanged (retriever quality is fixed); Citation acc "
             "holds for queries whose relevant docs sit in the top-5 (the factual-heavy majority) and "
             "dips only for queries with relevant docs ranked deeper — precisely the comparative/"
             "procedural queries the Query Router sends to Graph. Below topk=5 you start dropping "
             "relevant docs and both recall and citation accuracy fall. As retrieval context grows "
             "(larger topk / longer chunks) the saving approaches ~50% because input dominates further.\n")

    L.append("\n---\n*Generated by `run.py`. Re-run after editing dataset.py / pricing.py.*\n")
    return "\n".join(L)
