"""LLM cost accounting (F2).

Converts token usage into an estimated cost in CNY using DeepSeek's published
per-1M-token pricing. Prices are config-driven so they can be updated without a
code change (env override ``LLM_PRICING_OVERRIDE`` holding a JSON blob).

Pricing model (CNY per 1,000,000 tokens):

    model                       cached_input  uncached_input  output
    deepseek-v4-flash                  0.02            1.00      2.00
    deepseek-v4-pro                    0.10           12.00     24.00
    deepseek-v4-pro_discounted         0.025           3.00      6.00

The current usage payload from the API does not always tell us whether input
tokens were a cache hit or miss. When the breakdown is unknown we bill the whole
input at the *uncached* rate (the conservative / higher estimate) but keep a
``cached_input_tokens`` parameter so callers can split the cost once the API
exposes that detail.

``deepseek-chat`` is kept as a compatibility alias that maps onto the
``deepseek-v4-flash`` price tier, matching ``AIConfig.MODEL``'s default.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

# Per-1M-token prices in CNY. Keep keys lowercase for case-insensitive lookup.
DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {
        "cached_input": 0.02,
        "uncached_input": 1.0,
        "output": 2.0,
    },
    "deepseek-v4-pro": {
        "cached_input": 0.1,
        "uncached_input": 12.0,
        "output": 24.0,
    },
    "deepseek-v4-pro_discounted": {
        "cached_input": 0.025,
        "uncached_input": 3.0,
        "output": 6.0,
    },
}

# Compatibility aliases: legacy / API model names -> a key in the price table.
MODEL_ALIASES: dict[str, str] = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-pro",
}

_PER_MILLION = 1_000_000


def _load_price_overrides() -> dict[str, dict[str, float]]:
    """Merge any ``LLM_PRICING_OVERRIDE`` JSON over the built-in defaults.

    The override is a JSON object mapping model name -> partial price dict, e.g.
    ``{"deepseek-v4-flash": {"output": 2.5}}``. Unknown keys are ignored;
    malformed JSON is logged and dropped so a bad env var never breaks tracing.
    """
    raw = os.environ.get("LLM_PRICING_OVERRIDE", "").strip()
    if not raw:
        return DEFAULT_PRICES
    try:
        override = json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning("Ignoring invalid LLM_PRICING_OVERRIDE: %s", exc)
        return DEFAULT_PRICES
    if not isinstance(override, dict):
        logger.warning("LLM_PRICING_OVERRIDE must be a JSON object; ignoring.")
        return DEFAULT_PRICES

    merged = {model: dict(prices) for model, prices in DEFAULT_PRICES.items()}
    for model, prices in override.items():
        if not isinstance(prices, dict):
            continue
        key = str(model).lower()
        base = merged.get(key, {})
        for field in ("cached_input", "uncached_input", "output"):
            if field in prices:
                try:
                    base[field] = float(prices[field])
                except (TypeError, ValueError):
                    logger.warning(
                        "Bad price %r for %s.%s; ignoring.", prices[field], model, field
                    )
        merged[key] = base
    return merged


def resolve_price_tier(model: str | None) -> str | None:
    """Map a model name (possibly an alias) to a key in the price table.

    Returns ``None`` when the model is unknown so callers can skip costing
    rather than emit a misleading number.
    """
    if not model:
        return None
    key = model.strip().lower()
    key = MODEL_ALIASES.get(key, key)
    prices = _load_price_overrides()
    return key if key in prices else None


def compute_cost_cny(
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float | None:
    """Estimate the CNY cost of one LLM call.

    Args:
        model: model name or alias (e.g. ``deepseek-chat``).
        input_tokens: total prompt tokens for the call.
        output_tokens: completion tokens for the call.
        cached_input_tokens: portion of ``input_tokens`` known to be cache hits.
            When 0 (the common case today) the whole input is billed at the
            uncached rate.

    Returns:
        Estimated cost in CNY, or ``None`` if the model price is unknown.
    """
    tier = resolve_price_tier(model)
    if tier is None:
        return None

    prices = _load_price_overrides()[tier]
    input_tokens = max(int(input_tokens or 0), 0)
    output_tokens = max(int(output_tokens or 0), 0)
    cached = min(max(int(cached_input_tokens or 0), 0), input_tokens)
    uncached = input_tokens - cached

    cost = (
        cached * prices["cached_input"]
        + uncached * prices["uncached_input"]
        + output_tokens * prices["output"]
    ) / _PER_MILLION
    return round(cost, 6)
