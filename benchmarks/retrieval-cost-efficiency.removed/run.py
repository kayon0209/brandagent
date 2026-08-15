"""Entry point: compute the three cost-efficiency metrics and write RESULTS.md.

Run with the managed Python (no venv needed):

    python run.py

The module directory is added to sys.path so `retrieval_bench` imports cleanly
without installation.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from retrieval_bench.pricing import ILLUSTRATIVE_PRICING  # noqa: E402
from retrieval_bench import metrics as M  # noqa: E402


def main() -> None:
    pricing = ILLUSTRATIVE_PRICING
    mce = M.marginal_cost_efficiency(pricing)
    mixed, all_graph, savings, per = M.routing_mixed_cost(pricing)
    knob = M.cost_structure_and_knob(pricing)

    report = M.render_report(pricing, mce, mixed, all_graph, savings, per, knob)
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RESULTS.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(report)
    print(f"\n[written] {out_path}")


if __name__ == "__main__":
    main()
