"""Provider-independent call-put parity fitting kernels.

Provider adapters are responsible for quote normalization, rate selection,
settlement conventions, staleness policy, and any provider-specific bounds.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd


def _apply_discount_bounds(
    discount: float,
    lower_bound: float | None,
    upper_bound: float | None,
) -> float:
    if lower_bound is not None:
        discount = max(discount, lower_bound)
    if upper_bound is not None:
        discount = min(discount, upper_bound)
    return discount


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values)
    ordered_values = values[order]
    cumulative_weights = np.cumsum(weights[order])
    return float(ordered_values[np.searchsorted(cumulative_weights, 0.5 * cumulative_weights[-1])])


def infer_forward_discount_from_call_put_parity(
    call0: float,
    call1: float,
    put0: float,
    put1: float,
    strike0: float,
    strike1: float,
    discount: float = None,
    discfactor_upper_bound: float = None,
    discfactor_lower_bound: float = None,
) -> Tuple[float, float]:
    """Infer a forward and discount factor from two call-put parity observations."""
    if discount is None:
        discount = -((call0 - put0) - (call1 - put1)) / (strike0 - strike1)
        discount = _apply_discount_bounds(
            discount,
            discfactor_lower_bound,
            discfactor_upper_bound,
        )
    if not np.isfinite(discount) or discount <= 0.0:
        raise ValueError('discount must be finite and positive')

    forward = 0.5 * (((call0 - put0) + (call1 - put1)) / discount + strike0 + strike1)
    return float(forward), float(discount)


def _fit_parity_line(
    strikes: np.ndarray,
    call_minus_put: np.ndarray,
    quote_width: np.ndarray,
    *,
    discount: float | None,
    discfactor_lower_bound: float | None,
    discfactor_upper_bound: float | None,
    niters: int,
) -> tuple[float, float] | None:
    """Robustly fit ``C - P = D * (F - K)`` to aligned quote mids."""
    if discount is not None and (not np.isfinite(discount) or discount <= 0.0):
        raise ValueError('discount must be finite and positive')
    if discount is None and len(np.unique(strikes)) < 2:
        return None

    positive_widths = quote_width[np.isfinite(quote_width) & (quote_width > 0.0)]
    width_floor = max(float(np.nanmedian(positive_widths)) * 1e-3, 1e-8) if positive_widths.size else 1.0
    robust_scale_floor = max(float(np.nanmedian(positive_widths)) * 0.5, 1e-10) if positive_widths.size else 1e-10
    base_weights = np.reciprocal(np.maximum(quote_width, width_floor) ** 2)
    base_weights /= np.sum(base_weights)
    weights = base_weights.copy()
    strike_center = float(np.sum(base_weights * strikes))
    centered_strikes = strikes - strike_center
    fixed_discount = discount is not None

    for _ in range(max(int(niters), 1)):
        if fixed_discount:
            fitted_discount = float(discount)
            parity_at_center = _weighted_median(
                call_minus_put + fitted_discount * centered_strikes,
                weights,
            )
        else:
            design = np.column_stack((np.ones_like(centered_strikes), -centered_strikes))
            weighted_design = design * np.sqrt(weights)[:, None]
            weighted_target = call_minus_put * np.sqrt(weights)
            parity_at_center, fitted_discount = np.linalg.lstsq(
                weighted_design,
                weighted_target,
                rcond=None,
            )[0]
            fitted_discount = _apply_discount_bounds(
                float(fitted_discount),
                discfactor_lower_bound,
                discfactor_upper_bound,
            )
            parity_at_center = float(
                np.sum(weights * (call_minus_put + fitted_discount * centered_strikes))
            )

        residuals = call_minus_put - (parity_at_center - fitted_discount * centered_strikes)
        residual_center = float(np.median(residuals))
        robust_scale = max(
            1.4826 * float(np.median(np.abs(residuals - residual_center))),
            robust_scale_floor,
        )
        cutoff = 1.345 * robust_scale
        robust_weights = np.minimum(1.0, cutoff / np.maximum(np.abs(residuals), 1e-16))
        weights = base_weights * robust_weights
        weights /= np.sum(weights)

    if not np.isfinite(fitted_discount) or fitted_discount <= 0.0:
        return None
    forward = strike_center + parity_at_center / fitted_discount
    if not np.isfinite(forward) or forward <= 0.0:
        return None
    return float(forward), float(fitted_discount)


def imply_forward_discount_from_mark_prices(
    call_mark_prices: pd.Series,
    put_mark_prices: pd.Series,
    discfactor_upper_bound: float = None,
    discfactor_lower_bound: float = None,
    niters: int = 4,
    discount: float = None,
) -> Optional[Tuple[float, float]]:
    """Infer forward and discount from aligned call and put mark prices."""
    aligned = pd.concat(
        [call_mark_prices.rename('call'), put_mark_prices.rename('put')],
        axis=1,
        join='inner',
    ).dropna()
    if aligned.empty:
        return None
    aligned = aligned.sort_index()
    strikes = pd.to_numeric(aligned.index, errors='coerce').to_numpy(float)
    valid = np.isfinite(strikes)
    if not np.any(valid):
        return None
    return _fit_parity_line(
        strikes=strikes[valid],
        call_minus_put=(aligned['call'] - aligned['put']).to_numpy(float)[valid],
        quote_width=np.ones(np.count_nonzero(valid)),
        discount=discount,
        discfactor_lower_bound=discfactor_lower_bound,
        discfactor_upper_bound=discfactor_upper_bound,
        niters=niters,
    )


def imply_forward_discount_from_bid_ask_prices(
    calls_bid_ask: pd.DataFrame,
    put_bid_ask: pd.DataFrame,
    discfactor_upper_bound: float = None,
    discfactor_lower_bound: float = None,
    niters: int = 4,
    discount: float = None,
) -> Optional[Tuple[float, float]]:
    """Infer forward and discount from aligned call/put bid-ask quotes.

    Quote mids are fitted with inverse-spread weights and Huber reweighting.
    When ``discount`` is supplied, it is treated as an external rate anchor and
    only the forward is inferred from parity. Otherwise both terms are fitted,
    subject to the optional discount-factor bounds.
    """
    if calls_bid_ask.shape[1] < 2 or put_bid_ask.shape[1] < 2:
        raise ValueError('call and put frames must each contain bid and ask columns')

    calls = calls_bid_ask.iloc[:, :2].copy()
    puts = put_bid_ask.iloc[:, :2].copy()
    calls.columns = ['call_bid', 'call_ask']
    puts.columns = ['put_bid', 'put_ask']
    aligned = calls.join(puts, how='inner').dropna().sort_index()
    strikes = pd.to_numeric(aligned.index, errors='coerce').to_numpy(float)
    values = aligned.to_numpy(float)
    valid = (
        np.isfinite(strikes)
        & np.isfinite(values).all(axis=1)
        & (values[:, 0] >= 0.0)
        & (values[:, 1] >= values[:, 0])
        & (values[:, 2] >= 0.0)
        & (values[:, 3] >= values[:, 2])
        & ((values[:, 1] > 0.0) | (values[:, 0] > 0.0))
        & ((values[:, 3] > 0.0) | (values[:, 2] > 0.0))
    )
    if not np.any(valid):
        return None

    values = values[valid]
    call_minus_put = 0.5 * (values[:, 0] + values[:, 1] - values[:, 2] - values[:, 3])
    quote_width = values[:, 1] - values[:, 0] + values[:, 3] - values[:, 2]
    return _fit_parity_line(
        strikes=strikes[valid],
        call_minus_put=call_minus_put,
        quote_width=quote_width,
        discount=discount,
        discfactor_lower_bound=discfactor_lower_bound,
        discfactor_upper_bound=discfactor_upper_bound,
        niters=niters,
    )
