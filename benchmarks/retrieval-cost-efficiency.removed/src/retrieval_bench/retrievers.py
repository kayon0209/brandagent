"""Retrieval simulators and token/cost accounting.

No real vector store or LLM is touched. The simulators turn a ``Query`` and a
``topk_to_llm`` into (a) a recall number and (b) a token count, from which cost
is derived via the pricing table.
"""

from dataclasses import dataclass

from .dataset import Query
from .pricing import Pricing

# Token model -------------------------------------------------------------
PROMPT_TEMPLATE_TOKENS = 500  # fixed system+task prompt
CHUNK_TOKENS = 200  # average tokens per retrieved chunk
OUTPUT_TOKENS = 200  # generated answer length (kept short vs. retrieved context)
GRAPH_OVERHEAD_TOKENS = 1800  # entity-expansion LLM call + traversed subgraph context (fixed)
RETRIEVED_POOL = 20  # vector retriever returns a 20-deep candidate list


def recall_at_5(q: Query, graph: bool) -> float:
    """Fraction of gold docs present in the top-5 retrieved ranking."""
    ranks = q.gold_ranks_graph if graph else q.gold_ranks_vector
    hit = sum(1 for r in ranks if r <= 5)
    return hit / q.gold_size


def effective_recall(q: Query, topk_to_llm: int, graph: bool) -> float:
    """Recall of gold docs actually *reachable by the LLM*.

    The LLM only sees the top ``topk_to_llm`` retrieved chunks. A gold doc is
    usable only if its rank <= topk_to_llm. This is what drives both answer
    quality and citation accuracy.
    """
    ranks = q.gold_ranks_graph if graph else q.gold_ranks_vector
    hit = sum(1 for r in ranks if r <= topk_to_llm)
    return hit / q.gold_size


def context_tokens(q: Query, topk_to_llm: int, graph: bool) -> int:
    chunks = min(topk_to_llm, RETRIEVED_POOL)
    return PROMPT_TEMPLATE_TOKENS + chunks * CHUNK_TOKENS + (GRAPH_OVERHEAD_TOKENS if graph else 0)


def query_cost(q: Query, topk_to_llm: int, graph: bool, pricing: Pricing) -> float:
    inp = context_tokens(q, topk_to_llm, graph)
    out = OUTPUT_TOKENS
    return inp / 1e6 * pricing.input_per_million + out / 1e6 * pricing.output_per_million


@dataclass
class RouterDecision:
    intent: str
    scheme: str  # "vector" | "graph"
    reason: str


def route_query(intent: str) -> RouterDecision:
    """Query Router policy.

    Route to Graph only when plain vector retrieval cannot meet a Recall@5
    bar (here: comparative/procedural intents, where relation/step-chain docs
    live beyond the vector top-5). Factual queries stay on the cheap vector
    path.
    """
    if intent in ("comparative", "procedural"):
        return RouterDecision(intent, "graph", "vector Recall@5 below bar; Graph surfaces relation/step docs")
    return RouterDecision(intent, "vector", "gold already top-ranked; Graph adds cost, no recall")
