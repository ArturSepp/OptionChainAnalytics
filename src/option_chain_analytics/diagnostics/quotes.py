"""Observed quote quality without filtering, repairing or fitting observations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from collections.abc import Sequence

import numpy as np
import pandas as pd
import vanilla_option_pricers as bsm

from option_chain_analytics.option_chain import SliceColumn, SlicesChain
from option_chain_analytics.diagnostics.report import QuoteDiagnosticReport, _utc


@dataclass(frozen=True)
class QuoteDiagnosticConfig:
    """Explicit units, applicability and optional diagnostic thresholds.

    Parameters
    ----------
    price_unit : str
        Unit after conversion. Bounds/parity require ``USD per unit``.
    price_conversion : {'quoted', 'usd_per_unit'}
        The latter applies USD_MULTIPLIER once, never CONTRACT_SIZE.
    payoff, settlement : str
        Bounds/parity require ``standard_european`` and ``cash`` or ``physical``.
        Declaring these is the caller's verified normalization contract; a currency
        conversion alone does not establish standard-payoff equivalence.
    max_quote_age_seconds, max_snapshot_age_seconds : float, optional
        Nonnegative age thresholds relative to requested time; None leaves unchecked.
    max_relative_spread : float, optional
        Full spread / midpoint threshold, in decimal units.
    price_tolerance : float
        Nonnegative tolerance in the resulting price units.
    year_basis, delta_convention : str, optional
        Caller-declared conventions; unknown conventions stay absent.
    """

    price_unit: str
    price_conversion: str = "quoted"
    payoff: str = "unspecified"
    settlement: str = "unspecified"
    max_quote_age_seconds: float | None = None
    max_snapshot_age_seconds: float | None = None
    max_relative_spread: float | None = None
    price_tolerance: float = 1e-10
    year_basis: str | None = None
    delta_convention: str | None = None

    def __post_init__(self):
        """Reject ambiguous units or invalid thresholds."""
        if not isinstance(self.price_unit, str) or not self.price_unit.strip():
            raise ValueError("price_unit must be explicit")
        if self.price_conversion not in ("quoted", "usd_per_unit"):
            raise ValueError("price_conversion must be quoted or usd_per_unit")
        if self.price_conversion == "usd_per_unit" and self.price_unit != "USD per unit":
            raise ValueError('usd_per_unit requires price_unit="USD per unit"')
        if self.price_tolerance is None:
            raise ValueError("price_tolerance must be finite and nonnegative")
        for name in ("max_quote_age_seconds", "max_snapshot_age_seconds", "max_relative_spread", "price_tolerance"):
            value = getattr(self, name)
            if value is not None and (not np.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and nonnegative")


def _number(value) -> float:
    """Coerce malformed numeric observations to unavailable evidence."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _time(value):
    """Read a row timestamp without silently assigning a timezone."""
    try:
        return _utc(value, "row time")
    except (TypeError, ValueError):
        return pd.NaT


def _summary(frame: pd.DataFrame) -> dict:
    """Aggregate observed availability and coverage, with explicit denominators."""
    valid = frame.valid_price.astype(bool)
    strikes = pd.to_numeric(frame.strike, errors="coerce")
    strikes = strikes[np.isfinite(strikes) & (strikes > 0)]
    result = dict(
        n_rows=len(frame),
        n_contracts=frame.contract.nunique(),
        n_strikes=strikes.nunique(),
        n_two_sided=int(valid.sum()),
        n_iv=int(frame.valid_iv.sum()),
        n_failed_rows=int(frame.n_failed_checks.gt(0).sum()),
        n_locked=int(frame.locked.sum()),
        n_zero_bid=int(frame.zero_bid.sum()),
        n_one_sided=int(frame.one_sided.sum()),
    )
    for field in ("spread", "relative_spread", "quote_age_seconds", "log_moneyness", "delta"):
        values = pd.to_numeric(frame[field], errors="coerce")
        values = values[np.isfinite(values)]
        result.update(
            {
                f"{field}_{name}": value
                for name, value in (
                    ("n", len(values)),
                    ("min", values.min()),
                    ("median", values.median()),
                    ("max", values.max()),
                )
            }
        )
    for field in ("bid_size", "ask_size", "open_interest"):
        values = pd.to_numeric(frame[field], errors="coerce")
        result[f"n_{field}"] = int((np.isfinite(values) & (values >= 0)).sum())
    result["strike_min"], result["strike_max"] = strikes.min(), strikes.max()
    pair_keys = ["underlying_index", "mat_id", "expiry", "strike", "exchange_time"]
    paired = frame.loc[valid & frame.optiontype.isin(["C", "P"])].groupby(pair_keys).optiontype.nunique()
    result["n_paired_strikes"] = int(paired.eq(2).sum())
    result["status"] = "not_checked" if frame.empty else ("fail" if result["n_failed_rows"] else "pass")
    return result


def diagnose_quotes(
    observations: pd.DataFrame | SlicesChain,
    *,
    config: QuoteDiagnosticConfig,
    requested_time: pd.Timestamp,
    source_time: pd.Timestamp | None = None,
    source_row_ids: Sequence[str] | None = None,
    target_maturities: Sequence[str] = (),
) -> QuoteDiagnosticReport:
    """Diagnose every raw snapshot row or every available reconstructed-chain row.

    Parameters
    ----------
    observations : pandas.DataFrame or SlicesChain
        A normalized snapshot before deduplication, or an existing chain whose
        earlier discarded rows are unavailable. Input is never changed.
    config : QuoteDiagnosticConfig
        Explicit conventions and thresholds. Missing fields remain visible.
    requested_time, source_time : pandas.Timestamp
        Aware request and actual snapshot times. Source time defaults to chain
        value_time for a chain; it is not inferred for a raw frame.
    source_row_ids : sequence of str, optional
        Unique stable identities. Default row positions are local to this input.
    target_maturities : sequence of str
        Maturity IDs whose absence should be recorded, without synthesizing quotes.

    Returns
    -------
    QuoteDiagnosticReport
        Quotes, per-row checks, expiry/side coverage, totals and target coverage.
        ``pass`` denotes a completed local check, never an arbitrage certificate.
    """
    requested = _utc(requested_time, "requested_time")
    is_chain = isinstance(observations, SlicesChain)
    if is_chain:
        source_time = observations.value_time if source_time is None else source_time
        frame = observations.options_df.copy(deep=True)
    elif isinstance(observations, pd.DataFrame):
        frame = observations.copy(deep=True)
    else:
        raise TypeError("observations must be a normalized frame or SlicesChain")
    source = None if source_time is None else _utc(source_time, "source_time")
    if source is not None and source > requested:
        raise ValueError("source snapshot must not be later than requested time")
    ids = list(source_row_ids) if source_row_ids is not None else [f"row:{i}" for i in range(len(frame))]
    if len(ids) != len(frame) or any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("source_row_ids must be unique nonempty strings aligned with observations")
    frame = frame.reindex(columns=[c.value for c in SliceColumn]).reset_index(drop=True)
    duplicates = frame.contract.notna() & frame.contract.duplicated(keep=False)
    conflict = frame.groupby("contract", dropna=True).transform("nunique").gt(1).any(axis=1)
    checks, rows = [], []
    numeric = (
        "strike",
        "forward_price",
        "discount",
        "ttm",
        "bid_price",
        "ask_price",
        "bid_iv",
        "ask_iv",
        "bid_size",
        "ask_size",
        "open_interest",
        "usd_multiplier",
        "contract_size",
        "delta",
    )
    for i, raw in frame.iterrows():
        row = raw.to_dict()
        row.update({key: _number(row[key]) for key in numeric})
        row["source_row_id"] = ids[i]
        row["exchange_time"], row["expiry"] = _time(row["exchange_time"]), _time(row["expiry"])
        local = []

        def check(name, good=None, reason="", value=None, severity="error", status=None):
            state = status or ("not_checked" if good is None else ("pass" if good else "fail"))
            local.append(
                dict(
                    source_row_id=ids[i],
                    check=name,
                    status=state,
                    severity=severity,
                    reason=reason if state != "pass" else "",
                    value=value,
                )
            )

        for name in ("contract", "underlying_index", "mat_id"):
            check(name, pd.notna(row[name]) and bool(str(row[name]).strip()), "missing_identity")
        for name in ("strike", "forward_price", "discount", "ttm"):
            check(name, np.isfinite(row[name]) and row[name] > 0, f"invalid_{name}", row[name])
        check("optiontype", row["optiontype"] in ("C", "P"), "unsupported_optiontype")
        scale = row["usd_multiplier"] if config.price_conversion == "usd_per_unit" else 1.0
        scale_valid = np.isfinite(scale) and scale > 0
        check("price_conversion", scale_valid, "invalid_usd_multiplier", scale)
        row["price_scale"] = scale if scale_valid else np.nan
        row["quoted_bid"], row["quoted_ask"] = row["bid_price"], row["ask_price"]
        row["bid_price"], row["ask_price"] = (
            row["bid_price"] * row["price_scale"],
            row["ask_price"] * row["price_scale"],
        )
        bid, ask = row["bid_price"], row["ask_price"]
        finite = np.isfinite(bid) and np.isfinite(ask)
        check("two_sided_price", finite, "missing_or_nonfinite_price")
        check("nonnegative_price", bid >= 0 and ask >= 0 if finite else None, "negative_or_missing_price")
        check("uncrossed_price", bid <= ask if finite else None, "crossed_or_missing_price")
        row["valid_price"] = bool(finite and bid >= 0 and ask >= bid)
        row["locked"] = bool(row["valid_price"] and ask == bid)
        row["zero_bid"] = bool(np.isfinite(bid) and bid == 0)
        row["one_sided"] = bool(np.isfinite(bid) != np.isfinite(ask))
        row["spread"] = ask - bid if row["valid_price"] else np.nan
        mid = (bid + ask) / 2
        row["relative_spread"] = row["spread"] / mid if mid > 0 else np.nan
        ivb, iva = row["bid_iv"], row["ask_iv"]
        row["valid_iv"] = bool(np.isfinite(ivb) and np.isfinite(iva) and 0 < ivb <= iva)
        iv_available = not np.isnan(ivb) and not np.isnan(iva)
        check("iv", row["valid_iv"] if iv_available else None, "invalid_iv" if iv_available else "missing_iv")
        check(
            "duplicate_contract",
            not duplicates.iloc[i],
            "duplicate_conflict" if conflict.iloc[i] else "duplicate_identical",
            severity="warning",
        )
        quote_time, expiry = row["exchange_time"], row["expiry"]
        check(
            "exchange_time",
            None if pd.isna(quote_time) else quote_time <= (source or requested),
            "missing_or_future_exchange_time",
        )
        check("expiry", None if pd.isna(expiry) else expiry > requested, "missing_or_expired_instrument")
        row["quote_age_seconds"] = (requested - quote_time).total_seconds() if pd.notna(quote_time) else np.nan
        for name, value, threshold in (
            ("quote_age", row["quote_age_seconds"], config.max_quote_age_seconds),
            ("relative_spread", row["relative_spread"], config.max_relative_spread),
        ):
            check(
                name,
                None if threshold is None or not np.isfinite(value) else 0 <= value <= threshold,
                "threshold_not_configured_or_value_missing" if threshold is None or not np.isfinite(value) else name,
                value,
                severity="warning",
            )
        for name in ("bid_size", "ask_size", "open_interest"):
            value = row[name]
            check(name, value >= 0 if np.isfinite(value) else None, f"missing_or_negative_{name}", value, "warning")
        supported = config.payoff == "standard_european" and config.settlement in ("cash", "physical")
        inputs_valid = all(np.isfinite(row[k]) and row[k] > 0 for k in ("strike", "forward_price", "discount", "ttm"))
        if not supported or config.price_unit != "USD per unit":
            check("price_bounds", reason="payoff_settlement_or_units_not_verified", status="not_applicable")
        elif inputs_valid and row["valid_price"] and row["optiontype"] in ("C", "P"):
            # VIP has no exported price-bound helper. Its zero-volatility price gives
            # the lower bound; the upper bound is the discounted payoff cap.
            lower = bsm.compute_bsm_vanilla_price(
                forward=row["forward_price"],
                strike=row["strike"],
                ttm=row["ttm"],
                vol=0.0,
                optiontype=row["optiontype"],
                discfactor=row["discount"],
            )
            upper = row["discount"] * (row["forward_price"] if row["optiontype"] == "C" else row["strike"])
            margin = min(ask - lower, upper - bid)
            check("price_bounds", margin >= -config.price_tolerance, "quote_interval_outside_bounds", margin)
        else:
            check("price_bounds", reason="invalid_or_missing_inputs")
        row["log_moneyness"] = np.log(row["strike"] / row["forward_price"]) if inputs_valid else np.nan
        row["reason_codes"] = [r["reason"] for r in local if r["status"] == "fail"]
        row["n_failed_checks"] = sum(r["status"] == "fail" for r in local)
        row["n_unchecked"] = sum(r["status"] == "not_checked" for r in local)
        checks.extend(local)
        rows.append(row)
    columns = list(frame.columns) + [
        "source_row_id",
        "price_scale",
        "quoted_bid",
        "quoted_ask",
        "valid_price",
        "valid_iv",
        "locked",
        "zero_bid",
        "one_sided",
        "spread",
        "relative_spread",
        "quote_age_seconds",
        "log_moneyness",
        "reason_codes",
        "n_failed_checks",
        "n_unchecked",
    ]
    quotes = pd.DataFrame(rows, columns=columns)
    summary = _summary(quotes)
    snapshot_age = (requested - source).total_seconds() if source is not None else None
    threshold = config.max_snapshot_age_seconds
    summary.update(
        snapshot_age_seconds=snapshot_age,
        snapshot_age_status="not_checked"
        if threshold is None or snapshot_age is None
        else ("pass" if snapshot_age <= threshold else "fail"),
    )
    groups = []
    keys = ["underlying_index", "mat_id", "expiry", "optiontype"]
    for key, group in quotes.groupby(keys, dropna=False, sort=True):
        groups.append(dict(zip(keys, key)) | _summary(group))
    targets = pd.DataFrame(
        [
            dict(
                mat_id=str(mat),
                status="pass" if str(mat) in set(quotes.mat_id) else "not_checked",
                reason="" if str(mat) in set(quotes.mat_id) else "missing_target_maturity",
            )
            for mat in target_maturities
        ],
        columns=["mat_id", "status", "reason"],
    )
    return QuoteDiagnosticReport.from_tables(
        dict(
            quotes=quotes,
            checks=pd.DataFrame(checks, columns=["source_row_id", "check", "status", "severity", "reason", "value"]),
            expiries=pd.DataFrame(groups),
            summary=pd.DataFrame([summary]),
            targets=targets,
        ),
        dict(
            kind="quote_quality",
            config=asdict(config),
            requested_time=requested,
            source_time=source,
            input_scope="reconstructed_chain" if is_chain else "snapshot_before_deduplication",
            pre_reconstruction_counts="not_available" if is_chain else "provided",
            row_identity="caller_supplied" if source_row_ids is not None else "input_position",
            iv_unit="decimal",
            ttm_unit="years",
            age_unit="seconds",
            filters_applied=False,
        ),
    )
