"""Retrieval cost-efficiency benchmark.

A self-contained, dependency-free harness that quantifies the cost/quality
trade-offs of a RAG retrieval stack:

  1. Marginal cost efficiency of Graph augmentation (ΔRecall@5 per 1% cost)
  2. Post-routing mixed cost vs. "all-Graph-on" cost
  3. Cost-structure breakdown + a topk_to_llm cost-reduction knob experiment

The retrieval-quality model is a *parameterized, deterministic simulator*.
Plug in a real retriever, a real labelled dataset and your provider's pricing
to obtain production numbers. See README.md for methodology and honest labeling.
"""

__version__ = "0.1.0"
