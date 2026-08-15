"""Built-in evaluation dataset (small, labelled, deterministic).

Each query carries the positions (1-based) of its gold (relevant) documents in
two rankings:

  * ``gold_ranks_vector`` -- positions in the plain vector-retrieval ranking
  * ``gold_ranks_graph``  -- positions in the Graph-augmented ranking
    (a superset that surfaces entity/relation-linked docs into the top-5)

This lets the simulator compute Recall@5 and effective recall at any
``topk_to_llm`` without a real vector store. Replace ``DATASET`` with your own
labelled queries (same shape) for production reporting.

Intent mix mirrors a realistic brand-knowledge RAG traffic profile:
factual queries dominate; comparative/procedural are rarer but benefit most
from Graph augmentation.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Query:
    id: str
    intent: str  # "factual" | "comparative" | "procedural"
    gold_ranks_vector: list[int]
    gold_ranks_graph: list[int]

    @property
    def gold_size(self) -> int:
        # Graph ranking is a superset of vector ranking, so use it for the
        # denominator (it contains every relevant doc).
        return len(set(self.gold_ranks_graph))


DATASET: list[Query] = [
    # --- factual: Graph adds nothing, gold already top-ranked ---
    Query("F1", "factual", [1, 2, 3], [1, 2, 3]),
    Query("F2", "factual", [1, 2, 4], [1, 2, 4]),
    Query("F3", "factual", [1, 2, 3, 5], [1, 2, 3, 5]),
    Query("F4", "factual", [1, 2, 4, 5], [1, 2, 4, 5]),
    # --- comparative: Graph surfaces relation docs at ranks 4,5 ---
    Query("C1", "comparative", [1, 2, 3, 6], [1, 2, 3, 4, 5, 6]),
    Query("C2", "comparative", [1, 2, 3, 7], [1, 2, 3, 4, 5, 7]),
    Query("C3", "comparative", [2, 3, 4, 8], [1, 2, 3, 4, 5, 8]),
    Query("C4", "comparative", [1, 3, 5, 7], [1, 3, 4, 5, 7]),
    # --- procedural: Graph surfaces step-chain docs; some gold runs deeper ---
    Query("P1", "procedural", [1, 2, 6], [1, 2, 4, 5, 6]),
    Query("P2", "procedural", [1, 2, 7], [1, 2, 4, 5, 7]),
    Query("P3", "procedural", [2, 3, 8], [1, 2, 3, 4, 8]),
    Query("P4", "procedural", [1, 3, 9], [1, 3, 4, 5, 9]),
]

# Realistic traffic mix used for the mixed-cost computation.
INTENT_PROPORTIONS: dict[str, float] = {
    "factual": 0.50,
    "comparative": 0.30,
    "procedural": 0.20,
}
