"""Provider pricing model.

Costs are computed from token counts produced by the retrievers, using a
pricing table. The default table is *illustrative* -- swap in your real
provider rates (e.g. GLM-4-Flash, GPT-4o-mini, Claude Haiku) to get
production-accurate numbers.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Pricing:
    input_per_million: float  # USD per 1M input tokens
    output_per_million: float  # USD per 1M output tokens
    label: str


# Illustrative mid-tier pricing (roughly GPT-4o-mini / GLM-4-Flash ballpark).
# Replace with real rates for production reporting.
ILLUSTRATIVE_PRICING = Pricing(
    input_per_million=0.10,
    output_per_million=0.30,
    label="illustrative-mid-tier",
)
