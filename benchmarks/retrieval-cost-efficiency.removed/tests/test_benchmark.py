"""Unit tests for the retrieval cost-efficiency benchmark.

Run with the managed Python (no venv / no pytest needed):

    python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from retrieval_bench.pricing import ILLUSTRATIVE_PRICING  # noqa: E402
from retrieval_bench import metrics as M  # noqa: E402
from retrieval_bench.retrievers import recall_at_5, route_query  # noqa: E402


class TestRecall(unittest.TestCase):
    def test_factual_graph_adds_no_recall(self):
        mce = {r["intent"]: r for r in M.marginal_cost_efficiency(ILLUSTRATIVE_PRICING)}
        self.assertAlmostEqual(mce["factual"]["d_recall_pp"], 0.0, places=4)

    def test_comparative_procedural_graph_helps(self):
        mce = {r["intent"]: r for r in M.marginal_cost_efficiency(ILLUSTRATIVE_PRICING)}
        self.assertGreater(mce["comparative"]["d_recall_pp"], 0)
        self.assertGreater(mce["procedural"]["d_recall_pp"], 0)


class TestMarginalCostEfficiency(unittest.TestCase):
    def test_factual_marginal_near_zero(self):
        mce = {r["intent"]: r for r in M.marginal_cost_efficiency(ILLUSTRATIVE_PRICING)}
        # Graph buys ~0 recall for factual -> default-off signal
        self.assertLess(abs(mce["factual"]["marginal"]), 0.01)

    def test_graph_cost_is_higher(self):
        mce = {r["intent"]: r for r in M.marginal_cost_efficiency(ILLUSTRATIVE_PRICING)}
        for r in mce.values():
            self.assertGreater(r["cost_graph"], r["cost_vec"])


class TestRouting(unittest.TestCase):
    def test_router_policy(self):
        self.assertEqual(route_query("factual").scheme, "vector")
        self.assertEqual(route_query("comparative").scheme, "graph")
        self.assertEqual(route_query("procedural").scheme, "graph")

    def test_routing_saves_cost(self):
        mixed, all_graph, savings, _ = M.routing_mixed_cost(ILLUSTRATIVE_PRICING)
        self.assertLess(mixed, all_graph)
        self.assertGreater(savings, 0)
        self.assertLess(savings, 100)


class TestCostKnob(unittest.TestCase):
    def test_cost_decreases_with_topk(self):
        knob = M.cost_structure_and_knob(ILLUSTRATIVE_PRICING)
        costs = [r["avg_cost"] for r in knob]
        self.assertGreater(costs[0], costs[1])
        self.assertGreater(costs[1], costs[2])

    def test_input_token_share_dominant(self):
        knob = M.cost_structure_and_knob(ILLUSTRATIVE_PRICING)
        for r in knob:
            self.assertGreater(r["input_pct"], 80)

    def test_topk5_preserves_citation_better_than_topk3(self):
        knob = M.cost_structure_and_knob(ILLUSTRATIVE_PRICING)
        by_topk = {r["topk"]: r for r in knob}
        # shrinking 10->5 should cost far less than 10->3 while hurting citation less
        drop_10_5 = 1 - by_topk[5]["citation_acc"] / by_topk[10]["citation_acc"]
        drop_10_3 = 1 - by_topk[3]["citation_acc"] / by_topk[10]["citation_acc"]
        self.assertLessEqual(drop_10_5, drop_10_3)


if __name__ == "__main__":
    unittest.main()
