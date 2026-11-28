"""Fetch a private EUR/USD BDP snapshot, or reconstruct its five mid-IV pillars offline."""

import argparse
from enum import Enum
from pathlib import Path

import numpy as np
import pandas as pd

from option_chain_analytics.local_path import get_resource_path


TENORS = ("1M", "2M", "3M", "6M", "1Y")
QUOTE_TYPES = ("V", "10R", "25R", "10B", "25B")
PRIVATE_DATA = Path(get_resource_path()) / "fx_smile"


def _forward_security(tenor):
    # Bloomberg quotes the one-year forward under 12M and its volatility under 1Y.
    return f"EURUSD{'12M' if tenor == '1Y' else tenor} Curncy"


def _securities(tenors):
    tickers = ["EURUSD Curncy", "SOFRRATE Index"]
    for tenor in tenors:
        tickers.extend(f"EURUSD{kind}{tenor} Curncy" for kind in QUOTE_TYPES)
        tickers.append(_forward_security(tenor))
    return tickers


def fetch_snapshot():
    """Save contemporaneous broker mids, option expiries, forward points and the USD rate proxy."""
    from bbg_fetch import bdp, disconnect

    fields = ["PX_MID", "PX_LAST", "LAST_UPDATE_DT", "FWD_SCALE", "MATURITY", "OPT_EXPIRE_DT", "NAME"]
    try:
        raw = bdp(_securities(TENORS), fields)
    finally:
        disconnect()
    if raw.empty:
        raise ValueError("Bloomberg returned no FX snapshot")
    at = pd.Timestamp.now(tz="UTC")
    raw["retrieved_at_utc"] = at.isoformat()
    PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
    path = PRIVATE_DATA / f"EURUSD_broker_mids_{at:%Y%m%dT%H%M%S%fZ}.csv"
    raw.to_csv(path, index_label="security")
    return path


def reconstruct(path):
    """Interpret BFY as a broker market strangle under the stated sample conventions."""
    from option_chain_analytics import FXSmileQuote, fx_smile_to_options_data

    raw = pd.read_csv(path, index_col="security")
    stamps = raw.retrieved_at_utc.unique()
    if len(stamps) != 1:
        raise ValueError("expected a single reference-data snapshot")
    at = pd.Timestamp(stamps[0])
    spot = raw.at["EURUSD Curncy", "px_mid"]
    usd_sofr = raw.at["SOFRRATE Index", "px_last"] / 100
    spot_settle = pd.Timestamp(raw.at["EURUSD Curncy", "maturity"])
    # Older snapshots requested only the first two tenors. A partially populated
    # five-tenor response must still fail rather than silently dropping a maturity.
    tenors = TENORS[:2] if set(raw.index) == set(_securities(TENORS[:2])) else TENORS
    smiles = []
    for tenor in tenors:
        securities = [f"EURUSD{kind}{tenor} Curncy" for kind in QUOTE_TYPES]
        wing_quotes = raw.reindex(securities)
        expiry_dates = wing_quotes.opt_expire_dt
        if (not np.isfinite(wing_quotes.px_mid).all() or expiry_dates.isna().any()
                or expiry_dates.nunique() != 1):
            raise ValueError(f"Missing mids or inconsistent option expiry dates for {tenor}")

        def mid(kind):
            return raw.at[f"EURUSD{kind}{tenor} Curncy", "px_mid"]

        fwd = raw.loc[_forward_security(tenor)]
        forward = spot + fwd.px_mid * 10.0 ** (-fwd.fwd_scale)
        delivery = pd.Timestamp(fwd.maturity)
        # Simple ACT/360 spot-to-delivery discount at the observed overnight rate.
        discount = 1 / (1 + usd_sofr * (delivery - spot_settle).days / 360)
        expiry = pd.Timestamp(expiry_dates.iloc[0])
        expiry = (expiry + pd.Timedelta(hours=10)).tz_localize("America/New_York")
        smiles.append(
            FXSmileQuote(
                pair="EURUSD",
                value_time=at,
                expiry=expiry,
                spot=spot,
                forward=forward,
                discount=discount,
                atm=mid("V") / 100,
                ms10=mid("10B") / 100,
                ms25=mid("25B") / 100,
                rr10=mid("10R") / 100,
                rr25=mid("25R") / 100,
                atm_convention="delta_neutral",
                delta_convention="spot",
                source="Bloomberg PX_MID; BFY interpreted as market strangle; USD SOFR flat ACT/360 discount",
            )
        )
    panel = fx_smile_to_options_data(smiles)
    panel.chain_ts["fx_tenor"] = panel.chain_ts.expiry.map({q.expiry: tenor for q, tenor in zip(smiles, tenors)})
    if not np.isfinite(panel.chain_ts.mark_iv).all():
        raise ValueError("incomplete reconstructed smile")
    return panel


class Locals(Enum):
    BLOOMBERG_FX_SMILE = "bloomberg_fx_smile"


def run_local(local: Locals) -> None:
    """Fetch a Bloomberg reference snapshot or replay an existing one."""
    if local != Locals.BLOOMBERG_FX_SMILE:
        raise ValueError(f"Unknown example {local}")
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--fetch", action="store_true", help="retrieve one snapshot from the Bloomberg Desktop API")
    actions.add_argument("--snapshot", type=Path, help="replay a saved broker snapshot offline")
    args = parser.parse_args()
    if args.fetch:
        print(fetch_snapshot())
    else:
        output = args.snapshot.with_name(args.snapshot.stem + "_derived.csv")
        reconstruct(args.snapshot).chain_ts.to_csv(output, index=False)
        print(output)


if __name__ == "__main__":
    run_local(local=Locals.BLOOMBERG_FX_SMILE)
