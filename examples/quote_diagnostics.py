"""Offline synthetic quote defects, parity and point-in-time provenance."""

from enum import Enum

import pandas as pd

from option_chain_analytics import OptionsDataDFs, generate_simulated_options_data
from option_chain_analytics.diagnostics import QuoteDiagnosticConfig, reconstruct_with_diagnostics
from option_chain_analytics.visuals.diagnostics import plot_quote_diagnostics


def diagnostic_example(multiplier: float = 1.0):
    """Return synthetic observations, unchanged legacy chain and diagnostic sidecar.

    A previous snapshot is 60 seconds old against an explicit 30-second threshold.
    One crossed market and one duplicate are injected. A multiplier of 100 changes
    quotation units only; contract size is independently 0.1.
    """
    data = generate_simulated_options_data(contract_size=0.1)
    frame = data.chain_ts.copy()
    time = data.get_timeindex()[0]
    selected = frame.index[frame.exchange_time.eq(time)]
    frame.loc[selected[4], "bid_price"] = frame.loc[selected[4], "ask_price"] + 0.5
    frame = pd.concat([frame, frame.loc[[selected[6]]]], ignore_index=True)
    frame[["bid_price", "ask_price", "mark_price"]] /= multiplier
    frame["usd_multiplier"] = multiplier
    data = OptionsDataDFs(frame, data.spot_data, data.ticker)
    config = QuoteDiagnosticConfig(
        "USD per unit",
        price_conversion="usd_per_unit",
        payoff="standard_european",
        settlement="cash",
        max_quote_age_seconds=30,
        max_snapshot_age_seconds=30,
        year_basis="ACT/365",
        delta_convention="discounted forward delta",
    )
    chain, report = reconstruct_with_diagnostics(
        data,
        time + pd.Timedelta(seconds=60),
        config=config,
        spread_floor=0.01,
        time_selection="previous",
        refit_parity=True,
    )
    assert report.table("counts").iloc[0].n_input == 31
    assert report.table("counts").iloc[0].n_slice_retained == 30
    assert report.table("counts").reconciled.all()
    assert report.table("checks").query('check == "uncrossed_price" and status == "fail"').shape[0] == 1
    assert report.table("summary").snapshot_age_status.iloc[0] == "fail"
    assert chain.value_time == time
    return data, chain, report


class Locals(Enum):
    """Offline numerical report and optional figure."""

    REPORT = 1
    PLOT = 2


def run_local(local: Locals):
    """Run the fixed synthetic example without any provider or local dataset."""
    _, _, report = diagnostic_example()
    print(report.table("counts").to_string(index=False))
    print(report.table("parity_expiries").to_string(index=False))
    if local == Locals.PLOT:
        return plot_quote_diagnostics(report)
    if local != Locals.REPORT:
        raise ValueError(local)
    return report


if __name__ == "__main__":
    run_local(local=Locals.REPORT)
