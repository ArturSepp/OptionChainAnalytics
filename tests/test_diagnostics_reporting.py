"""Whole-snapshot boundaries, row identity and count reconciliation."""

import importlib.util
from pathlib import Path
import json

import numpy as np
import pandas as pd

from option_chain_analytics import OptionsDataDFs, generate_simulated_options_data, create_chain_at_time
from option_chain_analytics.diagnostics import (
    QuoteDiagnosticConfig,
    QuoteDiagnosticReport,
    reconstruct_with_diagnostics,
)
from option_chain_analytics.visuals.diagnostics import plot_quote_diagnostics


CONFIG = QuoteDiagnosticConfig("USD per unit", payoff="standard_european", settlement="cash")


def test_duplicates_are_traced_through_both_legacy_boundaries():
    data = generate_simulated_options_data()
    frame = data.chain_ts.copy()
    duplicate = frame.iloc[[0]].copy()
    alias = frame.iloc[[2]].copy()
    alias["contract"] = "same-strike-alias"
    frame = pd.concat([frame, duplicate, alias], ignore_index=True)
    data = OptionsDataDFs(frame, data.spot_data, data.ticker)
    original = frame.copy(deep=True)
    time = data.get_timeindex()[0]
    chain, report = reconstruct_with_diagnostics(data, time, config=CONFIG, spread_floor=0.01)
    pd.testing.assert_frame_equal(data.chain_ts, original)
    legacy = create_chain_at_time(data, time)
    pd.testing.assert_frame_equal(chain.options_df, legacy.options_df)
    provenance = report.table("provenance")
    assert provenance.source_row_id.is_unique
    assert set(provenance.exclusion_reason) == {"", "duplicate_contract_keep_first", "duplicate_strike_keep_last"}
    counts = report.table("counts").iloc[0]
    assert (counts.n_input, counts.n_contract_unique, counts.n_slice_retained, counts.n_excluded) == (32, 31, 30, 2)
    assert counts.reconciled
    assert not any("source_row_id" in expiry.options_df for expiry in chain.expiry_slices.values())


def test_before_first_exact_missing_and_previous_selection_never_look_ahead():
    data = generate_simulated_options_data()
    time = data.get_timeindex()[0]
    for requested, policy in [(time - pd.Timedelta(seconds=1), "previous"), (time + pd.Timedelta(seconds=1), "exact")]:
        chain, report = reconstruct_with_diagnostics(
            data, requested, config=CONFIG, spread_floor=0.01, time_selection=policy
        )
        assert chain is None
        assert report.metadata["selection_reason"] == "no_permitted_snapshot"
        assert report.table("counts").n_input.iloc[0] == 0
        assert report.table("summary").status.iloc[0] == "not_checked"
    requested = time + pd.Timedelta(seconds=1)
    chain, report = reconstruct_with_diagnostics(
        data, requested, config=CONFIG, spread_floor=0.01, time_selection="previous"
    )
    assert chain.value_time == time
    assert pd.Timestamp(report.metadata["requested_time"]) == requested
    assert pd.Timestamp(report.metadata["source_time"]) == time
    assert report.table("quotes").quote_age_seconds.eq(1).all()
    restored = QuoteDiagnosticReport.from_dict(json.loads(json.dumps(report.to_dict(), allow_nan=False)))
    assert restored == report


def test_offline_example_and_figure_use_stored_results():
    path = Path(__file__).resolve().parents[1] / "examples" / "quote_diagnostics.py"
    spec = importlib.util.spec_from_file_location("quote_example", path)
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    _, _, normal = example.diagnostic_example(1)
    _, _, scaled = example.diagnostic_example(100)
    np.testing.assert_allclose(normal.table("quotes").bid_price, scaled.table("quotes").bid_price)
    figure = plot_quote_diagnostics(scaled)
    assert len(figure.axes) == 2
    import matplotlib.pyplot as plt

    plt.close(figure)
