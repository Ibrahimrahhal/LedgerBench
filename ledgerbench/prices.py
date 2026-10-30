"""
List prices in USD per million tokens, October 2026, so every system and the
judge are priced the same way. A model missing here is recorded as costing
nothing and flagged in the run's summary: add it before publishing a result.
"""

from __future__ import annotations

PRICES: dict[str, dict[str, float]] = {
    "gpt-5.4": {"input": 2.50, "cached_input": 0.25, "output": 15.00},
    "gpt-5.4-mini": {"input": 0.75, "cached_input": 0.075, "output": 4.50},
    "gpt-5.4-nano": {"input": 0.20, "cached_input": 0.02, "output": 1.25},
    "gpt-5.6-luna": {"input": 0.20, "cached_input": 0.02, "output": 1.20},
    "gpt-6-luna": {"input": 0.10, "cached_input": 0.01, "output": 0.50},
    "gpt-6.1-terra": {"input": 1.00, "cached_input": 0.05, "output": 5.00},
    "gpt-6-sol": {"input": 2.00, "cached_input": 0.20, "output": 10.00},
    "text-embedding-3-small": {"input": 0.02},
    "text-embedding-3-large": {"input": 0.13},
}


def price_key(model: str) -> str | None:
    """The price-list key for a model name, which the API may echo back with a date suffix."""
    if not model:
        return None
    if model in PRICES:
        return model
    base = model.split("-20")[0]
    return base if base in PRICES else None


def known(model: str) -> bool:
    return price_key(model) is not None


def cost_usd(model: str, tokens_in: int = 0, tokens_out: int = 0, cached_in: int = 0) -> float:
    """What a call cost. `tokens_in` includes the cached tokens, as the API reports it."""
    key = price_key(model)
    if key is None:
        return 0.0
    price = PRICES[key]
    uncached = max(tokens_in - cached_in, 0)
    return (
        uncached * price.get("input", 0.0)
        + cached_in * price.get("cached_input", price.get("input", 0.0))
        + tokens_out * price.get("output", 0.0)
    ) / 1_000_000


def usage_of(response) -> tuple[int, int, int]:
    """(tokens_in, tokens_out, cached_in) from an OpenAI chat, responses or embeddings result."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0, 0
    tokens_in = (
        getattr(usage, "prompt_tokens", None)
        or getattr(usage, "input_tokens", None)
        or getattr(usage, "total_tokens", 0)
        or 0
    )
    tokens_out = getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", 0) or 0
    details = getattr(usage, "prompt_tokens_details", None) or getattr(usage, "input_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) if details is not None else 0
    return int(tokens_in), int(tokens_out), int(cached or 0)
