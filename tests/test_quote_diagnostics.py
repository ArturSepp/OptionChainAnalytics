"""Independent quote defects, unavailable evidence and immutable reports."""

from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from option_chain_analytics import generate_simulated_options_data, create_chain_at_time
from option_chain_analytics.diagnostics import QuoteDiagnosticConfig, QuoteDiagnosticReport, diagnose_quotes


def fixture():
    data = generate_simulated_options_data(rate=-0.01)
    time = data.get_timeindex()[0]
    frame = data.chain_ts.loc[data.chain_ts.exchange_time.eq(time)].copy()
    config = QuoteDiagnosticConfig(
        "USD per unit",
        payoff="standard_european",
        settlement="cash",
        max_quote_age_seconds=30,
        max_snapshot_age_seconds=30,
        max_relative_spread=2,
    )
    return data, frame, time, config


@pytest.mark.parametrize(
    ("field", "value", "check", "reason"),
    [
        ("strike", -1, "strike", "invalid_strike"),
        ("forward_price", np.inf, "forward_price", "invalid_forward_price"),
        ("discount", 0, "discount", "invalid_discount"),
        ("ttm", 0, "ttm", "invalid_ttm"),
        ("bid_price", -1, "nonnegative_price", "negative_or_missing_price"),
        ("bid_price", 1e6, "uncrossed_price", "crossed_or_missing_price"),
        ("ask_price", np.nan, "two_sided_price", "missing_or_nonfinite_price"),
        ("ask_iv", -1, "iv", "invalid_iv"),
        ("optiontype", "X", "optiontype", "unsupported_optiontype"),
        ("open_interest", -1, "open_interest", "missing_or_negative_open_interest"),
    ],
)
def test_each_injected_defect_identifies_exact_row(field, value, check, reason):
    _, frame, time, config = fixture()
    frame.loc[frame.index[2], field] = value
    original = frame.copy(deep=True)
    report = diagnose_quotes(frame, config=config, requested_time=time, source_time=time)
    checks = report.table("checks")
    defect = checks.loc[checks.check.eq(check) & checks.status.eq("fail")]
    assert defect.source_row_id.tolist() == ["row:2"]
    assert defect.reason.tolist() == [reason]
    pd.testing.assert_frame_equal(frame, original)


def test_zero_bids_negative_rates_locked_and_missing_iv_are_separate():
    _, frame, time, config = fixture()
    frame.loc[frame.index[0], ["bid_price", "ask_price"]] = 0
    frame.loc[frame.index[0], ["bid_iv", "ask_iv"]] = np.nan
    report = diagnose_quotes(frame, config=config, requested_time=time, source_time=time)
    first = report.table("quotes").iloc[0]
    assert first.valid_price and first.zero_bid and first.locked and not first.valid_iv
    assert report.table("checks").query('check == "discount"').status.eq("pass").all()
    assert report.table("checks").query('source_row_id == "row:0" and check == "iv"').status.iloc[0] == "not_checked"


def test_timing_duplicates_thresholds_and_targets_remain_explicit():
    _, frame, time, config = fixture()
    frame.loc[frame.index[0], "exchange_time"] = time + pd.Timedelta(seconds=1)
    frame.loc[frame.index[1], "expiry"] = time - pd.Timedelta(seconds=1)
    duplicate = frame.iloc[[2]].copy()
    duplicate["bid_price"] += 0.01
    frame = pd.concat([frame, duplicate], ignore_index=True)
    report = diagnose_quotes(
        frame,
        config=config,
        requested_time=time + pd.Timedelta(seconds=60),
        source_time=time,
        target_maturities=("missing",),
    )
    checks = report.table("checks")
    assert checks.query('check == "duplicate_contract" and status == "fail"').source_row_id.tolist() == [
        "row:2",
        "row:30",
    ]
    assert checks.query('check == "duplicate_contract" and status == "fail"').reason.eq("duplicate_conflict").all()
    assert checks.query('check == "exchange_time" and status == "fail"').source_row_id.tolist() == ["row:0"]
    assert checks.query('check == "expiry" and status == "fail"').source_row_id.tolist() == ["row:1"]
    assert report.table("summary").snapshot_age_status.iloc[0] == "fail"
    assert report.table("targets").reason.iloc[0] == "missing_target_maturity"


def test_empty_missing_timing_and_unsupported_payoff_do_not_pass():
    _, frame, time, config = fixture()
    frame.exchange_time = pd.NaT
    frame.expiry = pd.NaT
    report = diagnose_quotes(frame, config=replace(config, payoff="inverse"), requested_time=time)
    checks = report.table("checks")
    assert checks.query('check == "exchange_time"').status.eq("not_checked").all()
    assert checks.query('check == "price_bounds"').status.eq("not_applicable").all()
    empty = diagnose_quotes(pd.DataFrame(), config=config, requested_time=time)
    assert empty.table("summary").status.iloc[0] == "not_checked"
    assert empty.table("quotes").empty
    assert empty.table("summary").n_rows.iloc[0] == 0


def test_price_bounds_and_exactly_once_multiplier_ignore_contract_size():
    _, frame, time, config = fixture()
    expected = frame[["bid_price", "ask_price"]].copy()
    frame[["bid_price", "ask_price"]] /= 100
    frame.usd_multiplier = 100
    frame.contract_size = 0.1
    report = diagnose_quotes(frame, config=replace(config, price_conversion="usd_per_unit"), requested_time=time)
    np.testing.assert_allclose(report.table("quotes")[["bid_price", "ask_price"]], expected)
    assert report.table("checks").query('check == "price_bounds"').status.eq("pass").all()
    frame.loc[frame.index[0], ["bid_price", "ask_price"]] = 200
    broken = diagnose_quotes(frame, config=replace(config, price_conversion="usd_per_unit"), requested_time=time)
    assert broken.table("checks").query('check == "price_bounds" and status == "fail"').source_row_id.tolist() == [
        "row:0"
    ]


def test_roundtrip_is_deterministic_and_independent_and_chain_scope_is_honest():
    data, frame, time, config = fixture()
    report = diagnose_quotes(frame, config=config, requested_time=time, source_time=time)
    payload = json.loads(json.dumps(report.to_dict(), allow_nan=False))
    clone = QuoteDiagnosticReport.from_dict(payload)
    assert clone == report == diagnose_quotes(frame, config=config, requested_time=time, source_time=time)
    payload["metadata"]["config"]["price_unit"] = "changed"
    table = clone.table("quotes")
    table.loc[0, "contract"] = "changed"
    assert report.table("quotes").contract.iloc[0] != "changed"
    assert report.metadata["config"]["price_unit"] == "USD per unit"
    chain_report = diagnose_quotes(create_chain_at_time(data, time), config=config, requested_time=time)
    assert chain_report.metadata["pre_reconstruction_counts"] == "not_available"
    with pytest.raises(ValueError, match="later"):
        diagnose_quotes(frame, config=config, requested_time=time, source_time=time + pd.Timedelta(seconds=1))
    with pytest.raises(ValueError, match="timezone"):
        diagnose_quotes(frame, config=config, requested_time=time.tz_localize(None))


def test_nullable_optiontype_is_reported_without_boolean_coercion():
    _, frame, time, config = fixture()
    frame.loc[frame.index[0], "optiontype"] = pd.NA
    result = diagnose_quotes(frame, config=config, requested_time=time)
    assert result.table("checks").query('check == "optiontype" and status == "fail"').source_row_id.tolist() == [
        "row:0"
    ]


def test_infinite_iv_is_invalid_and_missing_tolerance_is_rejected():
    _, frame, time, config = fixture()
    frame.loc[frame.index[0], "ask_iv"] = np.inf
    result = diagnose_quotes(frame, config=config, requested_time=time)
    assert result.table("checks").query('check == "iv" and status == "fail"').source_row_id.tolist() == ["row:0"]
    with pytest.raises(ValueError, match="price_tolerance"):
        replace(config, price_tolerance=None)


def test_pair_coverage_requires_matching_maturity_identity():
    _, frame, time, config = fixture()
    frame = frame.iloc[:2].copy()
    frame.loc[frame.index[1], "mat_id"] = "different-maturity-contract"
    result = diagnose_quotes(frame, config=config, requested_time=time)
    assert result.table("summary").n_paired_strikes.iloc[0] == 0
