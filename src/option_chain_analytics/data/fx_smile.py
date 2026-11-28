"""Reconstruct FX mid-IV pillars from ATM, risk reversal and broker market-strangle quotes.

Premiums are domestic (quote) currency per unit of foreign (base) currency.
The five-pillar smile is linear in log strike with flat extrapolation. Both
strangles are repriced on that same smile at their original market strikes.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import brentq, least_squares
from scipy.special import log_ndtr
import vanilla_option_pricers as vop

from option_chain_analytics.conventions import compute_time_to_maturity
from option_chain_analytics.option_chain import SliceColumn
from option_chain_analytics.option_data import OptionsDataDFs


@dataclass(frozen=True, kw_only=True)
class FXSmileQuote:
    """One dated FX broker smile. All volatilities and spreads are decimal.

    pair is BASEQUOTE, spot and forward are quote currency per base unit.
    discount is the domestic delivery discount; forward and spot must use
    consistent settlement conventions (foreign factor = discount * forward / spot).
    rr is call IV less put IV. ms is the common market-strangle IV less ATM.
    Supply timezone-aware observation and option expiry times, an explicit
    delta convention (forward, spot, forward_pa, spot_pa), an ATM convention
    (forward, spot, delta_neutral), and the source of the quotes.
    """

    pair: str
    value_time: pd.Timestamp
    expiry: pd.Timestamp
    spot: float
    forward: float
    discount: float
    atm: float
    rr10: float
    ms10: float
    rr25: float
    ms25: float
    delta_convention: str
    atm_convention: str
    source: str
    quote_to_usd: float | None = None


def _wing_strike(q: FXSmileQuote, t: float, signed_delta: float, vol: float) -> float:
    """Invert FX quote delta; premium-adjusted calls use the higher-strike root."""
    scale = q.discount * q.forward / q.spot if q.delta_convention.startswith("spot") else 1.0
    delta = signed_delta / scale
    if not 0 < abs(delta) < 1:
        raise ValueError("FX wing delta is unattainable with this foreign discount factor")
    if not q.delta_convention.endswith("_pa"):
        return vop.compute_bsm_strike_from_delta(ttm=t, forward=q.forward, delta=delta, vol=vol)

    # Premium adjustment changes forward delta to sign * (K/F) * N(sign*d2).
    std = vol * np.sqrt(t)
    sign = np.sign(delta)
    target = np.log(abs(delta))

    def residual(x):
        return x + log_ndtr(sign * (-x / std - 0.5 * std)) - target

    if delta > 0:
        # At maximum call delta, phi(d2)/N(d2) equals total volatility.
        def slope(z):
            return -0.5 * z * z - 0.5 * np.log(2 * np.pi) - log_ndtr(z) - np.log(std)

        z = brentq(slope, -max(10.0, 2 * std), max(40.0, np.sqrt(2 * abs(np.log(std))) + 2))
        left = -std * (z + 0.5 * std)
        if residual(left) <= 0:
            raise ValueError("premium-adjusted call delta is unattainable")
        right = max(1.0, left + std)
        while residual(right) > 0:
            right += max(1.0, abs(right))
    else:
        left, right = min(-1.0, target - 1.0), max(1.0, std * std)
        while residual(right) < 0:
            right *= 2
    return q.forward * np.exp(brentq(residual, left, right, xtol=1e-14))


def _smile_rows(q: FXSmileQuote):
    """Solve both fixed-strike broker premium equations on one five-pillar smile."""
    at, expiry = pd.Timestamp(q.value_time), pd.Timestamp(q.expiry)
    if at.tz is None or expiry.tz is None or expiry <= at:
        raise ValueError("require timezone-aware observation and later expiry")
    at, expiry = at.tz_convert("UTC"), expiry.tz_convert("UTC")
    t = compute_time_to_maturity(expiry, at)
    if len(q.pair) != 6 or not q.pair.isascii() or not q.pair.isalpha() or not q.pair.isupper() or not q.source.strip():
        raise ValueError("supply a BASEQUOTE currency pair and a quote source")
    if q.delta_convention not in ("spot", "forward", "spot_pa", "forward_pa"):
        raise ValueError("unknown FX delta convention")
    if q.atm_convention not in ("spot", "forward", "delta_neutral"):
        raise ValueError("unknown FX ATM convention")
    rr = np.array([q.rr10, q.rr25], dtype=float)
    strangle_vols = q.atm + np.array([q.ms10, q.ms25], dtype=float)
    levels = np.array([q.spot, q.forward, q.discount, q.atm, *strangle_vols])
    if not np.isfinite(rr).all() or not np.isfinite(levels).all() or min(levels) <= 0:
        raise ValueError("require finite quotes, positive outright vols, spot, forward and discount")
    if q.quote_to_usd is not None and (not np.isfinite(q.quote_to_usd) or q.quote_to_usd <= 0):
        raise ValueError("quote_to_usd must be finite and positive")
    multiplier = q.quote_to_usd
    if multiplier is None:
        multiplier = 1.0 if q.pair.endswith("USD") else (1 / q.spot if q.pair.startswith("USD") else np.nan)
    atm_strike = q.spot if q.atm_convention == "spot" else q.forward
    if q.atm_convention == "delta_neutral":
        exponent = -0.5 if q.delta_convention.endswith("_pa") else 0.5
        atm_strike *= np.exp(exponent * q.atm**2 * t)
    deltas = (0.10, 0.25)
    strangle_sides = ("P", "C")
    market_k = np.array([[_wing_strike(q, t, sign * d, v) for sign in (-1, 1)] for d, v in zip(deltas, strangle_vols)])

    def strangles(vols):
        return np.array(
            [
                sum(
                    vop.compute_bsm_vanilla_price(
                        forward=q.forward, strike=k, ttm=t, vol=v, optiontype=side, discfactor=q.discount
                    )
                    for k, v, side in zip(strikes, wing_vols, strangle_sides)
                )
                for strikes, wing_vols in zip(market_k, vols)
            ]
        )

    target = strangles(np.column_stack((strangle_vols, strangle_vols)))

    def pillars(means):
        puts, calls = means - rr / 2, means + rr / 2
        vols = np.array([puts[0], puts[1], q.atm, calls[1], calls[0]])
        strikes = np.array(
            [_wing_strike(q, t, -d, v) for d, v in zip(deltas, puts)]
            + [atm_strike]
            + [_wing_strike(q, t, d, v) for d, v in zip(deltas[::-1], calls[::-1])]
        )
        return strikes, vols

    def error(means):
        k, v = pillars(means)
        order = np.argsort(k)
        interpolated = np.interp(np.log(market_k), np.log(k[order]), v[order])
        return (strangles(interpolated) - target) / target

    if not np.isfinite(target).all() or min(target) <= 0:
        raise ValueError("market strangle premiums must be positive and finite")
    lower = abs(rr) / 2 + 1e-10
    solution = least_squares(
        error, np.maximum(strangle_vols, lower + 1e-5), bounds=(lower, np.inf), ftol=1e-13, gtol=1e-13, xtol=1e-13
    )
    strikes, vols = pillars(solution.x)
    if not solution.success or np.max(abs(solution.fun)) > 1e-8 or not np.all(np.diff(strikes) > 0):
        raise ValueError("FX quotes cannot be reconstructed as ordered pillars within market-strangle tolerance")
    sides = ["P", "P", "P" if atm_strike < q.forward else "C", "C", "C"]
    market_strikes = (market_k[0, 0], market_k[1, 0], np.nan, market_k[1, 1], market_k[0, 1])
    maturity = expiry.isoformat()
    for i, (pillar, k, vol, side) in enumerate(zip(("10P", "25P", "ATM", "25C", "10C"), strikes, vols, sides)):
        args = dict(forward=q.forward, strike=k, ttm=t, vol=vol, optiontype=side, discfactor=q.discount)
        price = vop.compute_bsm_vanilla_price(**args)
        forward_delta = vop.compute_bsm_vanilla_delta(**args)
        quote_delta = forward_delta / q.discount
        if q.delta_convention.endswith("_pa"):
            quote_delta -= price / (q.discount * q.forward)
        if q.delta_convention.startswith("spot"):
            quote_delta *= q.discount * q.forward / q.spot
        yield dict(
            contract=f"{q.pair}-{maturity}-{pillar}-{k:.17g}",
            exchange_time=at,
            underlying_index=q.pair,
            forward_price=q.forward,
            spot_price=q.spot,
            usd_multiplier=multiplier,
            mark_price=price,
            mark_iv=vol,
            delta=forward_delta,
            fx_quote_delta=quote_delta,
            mat_id=maturity,
            strike=k,
            optiontype=side,
            expiry=expiry,
            ttm=t,
            contract_size=1.0,
            discount=q.discount,
            quote_origin="derived_fx_smile_mid",
            quote_source=q.source,
            fx_pillar=pillar,
            atm_convention=q.atm_convention,
            delta_convention=q.delta_convention,
            atm=q.atm,
            rr10=q.rr10,
            rr25=q.rr25,
            ms10=q.ms10,
            ms25=q.ms25,
            market_strangle_strike=market_strikes[i],
        )


def fx_smile_to_options_data(quotes: Sequence[FXSmileQuote]) -> OptionsDataDFs:
    """Reconstruct five mid-only smile pillars per quoted expiry for one currency pair.

    Parameters
    ----------
    quotes : sequence of FXSmileQuote
        One record per observation and expiry, using annualised decimal IVs.
        A non-USD cross may supply quote_to_usd to enable USD-valued analytics.

    Returns
    -------
    OptionsDataDFs
        UTC panel containing source conventions, broker inputs, fixed strangle
        strikes and the five reconstructed marks in quote currency per base
        unit. Bid, ask, size and volume remain missing.

    Raises
    ------
    ValueError
        Invalid or inconsistent records, unattainable wing deltas, or quotes
        that cannot be repriced on ordered pillars within the premium tolerance.
    """
    quotes = tuple(quotes)
    pairs = {q.pair for q in quotes}
    if len(pairs) != 1:
        raise ValueError("supply one or more FX smiles for a single currency pair")
    rows = pd.DataFrame(row for q in quotes for row in _smile_rows(q))
    if rows.duplicated(["exchange_time", "expiry", "fx_pillar"]).any():
        raise ValueError("duplicate FX smile for observation and expiry")
    spots = rows[["exchange_time", "spot_price"]].drop_duplicates().set_index("exchange_time").sort_index()
    if not spots.index.is_unique:
        raise ValueError("inconsistent spot across expiries at one observation")
    required = [col.value for col in SliceColumn]
    panel = rows.reindex(columns=required + [col for col in rows if col not in required])
    return OptionsDataDFs(
        chain_ts=panel, spot_data=spots.rename(columns={"spot_price": "close"}), ticker=quotes[0].pair
    )
