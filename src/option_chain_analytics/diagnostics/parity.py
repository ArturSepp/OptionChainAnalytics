"""Synchronized bid/ask parity evidence and optional existing robust inference."""

from __future__ import annotations

import numpy as np
import pandas as pd

from option_chain_analytics.diagnostics.report import QuoteDiagnosticReport
from option_chain_analytics.utils.forward_discount import imply_forward_discount_from_bid_ask_prices


def diagnose_parity(
    quality: QuoteDiagnosticReport,
    *,
    spread_floor: float,
    refit: bool = False,
    discount_anchor: float | None = None,
    discount_bounds: tuple[float | None, float | None] = (None, None),
    max_condition_number: float = 1e8,
    forward_source: str = "declared_quote",
    discount_source: str = "declared_quote",
) -> QuoteDiagnosticReport:
    """Check declared parity separately from an optional robust refit.

    Parameters
    ----------
    quality : QuoteDiagnosticReport
        Quote report from diagnose_quotes, including normalized per-unit prices.
        Pairing requires identical underlying, expiry, maturity ID, strike and
        exchange time. Ambiguous duplicate legs and missing identity stay unchecked.
    spread_floor : float
        Positive floor for combined half-spread scaling, in report price units.
    refit : bool
        Call the existing spread-weighted, Huber-reweighted OCA fitter.
    discount_anchor : float, optional
        Positive external discount, held fixed during refitting.
    discount_bounds : tuple of optional float
        Explicit positive lower/upper bounds for the optional refit.
    max_condition_number : float
        Maximum dimensionless strike-design condition number for identifying D.
    forward_source, discount_source : str
        Provenance labels for supplied quote forwards and discounts.

    Returns
    -------
    QuoteDiagnosticReport
        Pair-level intervals/residuals, refit summaries and an eligibility map.
        Same-quote refits measure internal consistency, not independent validation.
    """
    # Accessors deserialize the immutable report. Snapshot metadata once so the
    # strike-pair loop does not repeatedly parse every quote and check table.
    metadata = quality.metadata
    if metadata.get("kind") != "quote_quality":
        raise ValueError("quality must be a quote-quality report")
    if not np.isfinite(spread_floor) or spread_floor <= 0:
        raise ValueError("spread_floor must be finite and positive")
    if not np.isfinite(max_condition_number) or max_condition_number <= 1:
        raise ValueError("max_condition_number must exceed one")
    lower, upper = discount_bounds
    for value in (discount_anchor, lower, upper):
        if value is not None and (not np.isfinite(value) or value <= 0):
            raise ValueError("discount values must be finite and positive")
    if lower is not None and upper is not None and lower > upper:
        raise ValueError("discount bounds must be ordered")
    if discount_anchor is not None and (
        (lower is not None and discount_anchor < lower) or (upper is not None and discount_anchor > upper)
    ):
        raise ValueError("discount anchor conflicts with supplied bounds")
    if not forward_source or not discount_source:
        raise ValueError("forward and discount provenance must be explicit")
    config = metadata["config"]
    supported = (
        config["payoff"] == "standard_european"
        and config["settlement"] in ("cash", "physical")
        and config["price_unit"] == "USD per unit"
    )
    quotes = quality.table("quotes")
    numeric = ["strike", "forward_price", "discount", "ttm", "bid_price", "ask_price"]
    quotes[numeric] = quotes[numeric].astype(float)
    keys = ["underlying_index", "mat_id", "expiry", "exchange_time", "strike"]
    rows, eligibility = [], []
    for key, group in quotes.groupby(keys, dropna=False, sort=True):
        record = dict(zip(keys, key))
        calls, puts = group.loc[group.optiontype.eq("C")], group.loc[group.optiontype.eq("P")]
        reason = ""
        if not supported:
            reason = "payoff_settlement_or_units_not_verified"
        elif any(pd.isna(v) or str(v).strip() == "" for v in key):
            reason = "missing_pair_identity"
        elif len(calls) != 1 or len(puts) != 1:
            reason = "unmatched_strike" if calls.empty or puts.empty else "duplicate_pair_legs"
        elif len(group) != 2:
            reason = "unsupported_pair_leg"
        else:
            legs = pd.concat([calls, puts])
            if not legs.valid_price.all():
                reason = "invalid_quote_leg"
            elif (
                not np.isfinite(legs[numeric]).all().all()
                or (legs[["strike", "forward_price", "discount", "ttm"]] <= 0).any().any()
            ):
                reason = "invalid_pricing_inputs"
            elif not np.isclose(
                calls.forward_price.iloc[0], puts.forward_price.iloc[0], rtol=1e-10, atol=1e-12
            ) or not np.isclose(calls.discount.iloc[0], puts.discount.iloc[0], rtol=1e-10, atol=1e-12):
                reason = "inconsistent_declared_forward_or_discount"
            elif (
                pd.Timestamp(key[3]) > pd.Timestamp(metadata["requested_time"])
                or (
                    metadata["source_time"] is not None
                    and pd.Timestamp(key[3]) > pd.Timestamp(metadata["source_time"])
                )
                or pd.Timestamp(key[2]) <= pd.Timestamp(metadata["requested_time"])
            ):
                reason = "ineligible_observation_or_expiry_time"
        record.update(
            source_row_ids=group.source_row_id.tolist(),
            status="not_applicable" if not supported else "not_checked",
            reason=reason,
            lower=np.nan,
            upper=np.nan,
            declared_parity=np.nan,
            mid_residual=np.nan,
            scaled_residual=np.nan,
            distance_outside=np.nan,
            refit_eligible=False,
            refit_residual=np.nan,
            fitted_forward=np.nan,
            fitted_discount=np.nan,
        )
        if not reason:
            call, put = calls.iloc[0], puts.iloc[0]
            interval_lower = call.bid_price - put.ask_price
            interval_upper = call.ask_price - put.bid_price
            parity = call.discount * (call.forward_price - call.strike)
            residual = (interval_lower + interval_upper) / 2 - parity
            distance = max(interval_lower - parity, parity - interval_upper, 0.0)
            record.update(
                lower=interval_lower,
                upper=interval_upper,
                declared_parity=parity,
                mid_residual=residual,
                scaled_residual=residual / max((interval_upper - interval_lower) / 2, spread_floor),
                distance_outside=distance,
                status="pass" if distance <= config["price_tolerance"] else "fail",
                reason="" if distance <= config["price_tolerance"] else "outside_parity_interval",
                call_bid=call.bid_price,
                call_ask=call.ask_price,
                put_bid=put.bid_price,
                put_ask=put.ask_price,
                refit_eligible=bool(call.ask_price > 0 and put.ask_price > 0),
            )
        rows.append(record)
        for row_id in group.source_row_id:
            eligibility.append(
                dict(
                    source_row_id=row_id,
                    pair_index=len(rows) - 1,
                    eligible=record["refit_eligible"],
                    reason=reason or ("" if record["refit_eligible"] else "zero_option_interval"),
                )
            )
    pair_columns = keys + [
        "source_row_ids",
        "status",
        "reason",
        "lower",
        "upper",
        "declared_parity",
        "mid_residual",
        "scaled_residual",
        "distance_outside",
        "refit_eligible",
        "refit_residual",
        "fitted_forward",
        "fitted_discount",
        "call_bid",
        "call_ask",
        "put_bid",
        "put_ask",
    ]
    pairs = pd.DataFrame(rows, columns=pair_columns)
    summaries = []
    for key, group in pairs.groupby(keys[:-1], dropna=False, sort=True):
        valid = group.loc[group.refit_eligible.astype(bool)]
        strikes = valid.strike.to_numpy(float)
        condition = np.inf
        if len(strikes) >= 2:
            # Scale by typical strike, not strike range: near-coincident strikes
            # must remain visibly ill-conditioned rather than being normalized away.
            x = (strikes - np.mean(strikes)) / max(abs(np.mean(strikes)), 1.0)
            condition = float(np.linalg.cond(np.column_stack([np.ones(len(x)), x])))
        fit_result = None
        reason = "refit_not_requested"
        if refit:
            if valid.empty:
                reason = "no_eligible_pairs"
            elif discount_anchor is None and condition > max_condition_number:
                reason = "discount_unidentified"
            else:
                calls = valid.set_index("strike")[["call_bid", "call_ask"]]
                puts = valid.set_index("strike")[["put_bid", "put_ask"]]
                fit_result = imply_forward_discount_from_bid_ask_prices(
                    calls, puts, discount=discount_anchor, discfactor_lower_bound=lower, discfactor_upper_bound=upper
                )
                reason = "" if fit_result is not None else "robust_fit_failed"
        forward, discount = fit_result if fit_result is not None else (np.nan, np.nan)
        if fit_result is not None:
            pairs.loc[valid.index, "refit_residual"] = (valid.lower + valid.upper) / 2 - discount * (
                forward - valid.strike
            )
            pairs.loc[valid.index, ["fitted_forward", "fitted_discount"]] = [forward, discount]
        summaries.append(
            dict(zip(keys[:-1], key))
            | dict(
                n_pairs=len(group),
                n_eligible=len(valid),
                used_strikes=strikes.tolist() if fit_result is not None else [],
                rejected_strikes=group.loc[~group.refit_eligible.astype(bool), "strike"].tolist(),
                condition_number=condition,
                refit_status="pass" if fit_result is not None else "not_checked",
                refit_reason=reason,
                fitted_forward=forward,
                fitted_discount=discount,
                n_declared_fail=int(group.status.eq("fail").sum()),
                n_declared_checked=int(group.status.isin(["pass", "fail"]).sum()),
            )
        )
    return QuoteDiagnosticReport.from_tables(
        dict(
            pairs=pairs,
            expiries=pd.DataFrame(summaries),
            eligibility=pd.DataFrame(eligibility, columns=["source_row_id", "pair_index", "eligible", "reason"]),
        ),
        dict(
            kind="parity",
            config=config,
            requested_time=metadata["requested_time"],
            source_time=metadata["source_time"],
            spread_floor=spread_floor,
            refit=refit,
            discount_anchor=discount_anchor,
            discount_bounds=discount_bounds,
            max_condition_number=max_condition_number,
            forward_source=forward_source,
            discount_source=discount_source,
            robust_weights="internal to existing fitter; not rejection flags",
            executable_arbitrage=False,
        ),
    )
