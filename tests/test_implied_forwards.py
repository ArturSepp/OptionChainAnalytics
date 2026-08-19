from __future__ import annotations

import numpy as np
import pandas as pd

from option_chain_analytics.fitters import (
    imply_forward_discount_from_bid_ask_prices as exported_bid_ask_fitter,
)
from option_chain_analytics.fitters.forward_discount import (
    imply_forward_discount_from_bid_ask_prices,
)


def _parity_quotes(
    *,
    forward: float,
    discount: float,
    strikes: np.ndarray,
    half_spread: float = 0.01,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    parity = discount * (forward - strikes)
    calls = np.maximum(parity, 0.0) + 2.0
    puts = calls - parity
    call_quotes = pd.DataFrame({'bid': calls - half_spread, 'ask': calls + half_spread}, index=strikes)
    put_quotes = pd.DataFrame({'bid': puts - half_spread, 'ask': puts + half_spread}, index=strikes)
    return call_quotes, put_quotes


def test_provider_independent_fitter_is_exported_without_optional_solver() -> None:
    assert exported_bid_ask_fitter is imply_forward_discount_from_bid_ask_prices


def test_parity_fit_recovers_exact_forward_and_discount() -> None:
    strikes = np.arange(90.0, 115.0, 5.0)
    calls, puts = _parity_quotes(forward=102.0, discount=0.98, strikes=strikes)

    result = imply_forward_discount_from_bid_ask_prices(calls, puts)

    assert result is not None
    forward, discount = result
    assert np.isclose(forward, 102.0, atol=1e-12)
    assert np.isclose(discount, 0.98, atol=1e-12)


def test_external_discount_anchor_is_preserved_under_put_price_distortion() -> None:
    strikes = np.arange(85.0, 120.0, 5.0)
    calls, puts = _parity_quotes(forward=102.0, discount=0.98, strikes=strikes)
    puts.loc[115.0, ['bid', 'ask']] += 2.5

    result = imply_forward_discount_from_bid_ask_prices(calls, puts, discount=0.98, niters=8)

    assert result is not None
    forward, discount = result
    assert discount == 0.98
    assert np.isclose(forward, 102.0, atol=0.1)


def test_discount_bound_is_enforced_after_robust_regression() -> None:
    strikes = np.arange(90.0, 115.0, 5.0)
    calls, puts = _parity_quotes(forward=102.0, discount=1.2, strikes=strikes)

    result = imply_forward_discount_from_bid_ask_prices(
        calls,
        puts,
        discfactor_upper_bound=1.0,
    )

    assert result is not None
    _, discount = result
    assert discount == 1.0
