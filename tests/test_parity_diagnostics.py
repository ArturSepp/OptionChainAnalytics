"""Hand-computed parity intervals, robust inference and applicability gates."""

from dataclasses import replace
import numpy as np
import pandas as pd
import pytest

from option_chain_analytics import generate_simulated_options_data
from option_chain_analytics.diagnostics import QuoteDiagnosticConfig, diagnose_quotes, diagnose_parity


def fixture(strikes=(90.0, 95.0, 100.0, 105.0, 110.0), multiplier=1):
    data = generate_simulated_options_data()
    time = data.get_timeindex()[0]
    frame = data.chain_ts.loc[data.chain_ts.exchange_time.eq(time)].iloc[: 2 * len(strikes)].copy()
    frame["mat_id"], frame["expiry"] = "fixture", time + pd.Timedelta(days=90)
    frame["strike"] = np.repeat(strikes, 2)
    frame["forward_price"], frame["discount"] = 102.0, 1.02
    for i, row in frame.iterrows():
        # Hand parity: C = max(D(F-K), 0) + 2, P = C - D(F-K).
        parity = 1.02 * (102 - row.strike)
        price = max(parity, 0) + 2 - (parity if row.optiontype == "P" else 0)
        frame.loc[i, ["bid_price", "ask_price"]] = np.array([price - 0.01, price + 0.01]) / multiplier
    frame["usd_multiplier"], frame["contract_size"] = multiplier, 0.1
    config = QuoteDiagnosticConfig(
        "USD per unit", price_conversion="usd_per_unit", payoff="standard_european", settlement="cash"
    )
    return frame, time, config


def report(frame, time, config, **kwargs):
    return diagnose_parity(
        diagnose_quotes(frame, config=config, requested_time=time, source_time=time), spread_floor=0.005, **kwargs
    )


@pytest.mark.parametrize("multiplier", [1, 100])
def test_independent_parity_intervals_and_free_discount_recovery(multiplier):
    frame, time, config = fixture(multiplier=multiplier)
    result = report(frame, time, config, refit=True)
    pairs = result.table("pairs")
    reference = 1.02 * (102 - pairs.strike)
    np.testing.assert_allclose(pairs.lower, reference - 0.02, atol=1e-12)
    np.testing.assert_allclose(pairs.upper, reference + 0.02, atol=1e-12)
    assert pairs.status.eq("pass").all()
    summary = result.table("expiries").iloc[0]
    assert summary.fitted_forward == pytest.approx(102)
    assert summary.fitted_discount == pytest.approx(1.02)
    assert summary.n_eligible == 5


def test_outlier_and_fixed_discount_are_reported_separately():
    frame, time, config = fixture()
    frame.loc[frame.index[-1], ["bid_price", "ask_price"]] += 2
    result = report(frame, time, config, refit=True, discount_anchor=1.02)
    pairs = result.table("pairs")
    assert pairs.loc[pairs.status.eq("fail"), "strike"].tolist() == [110]
    assert pairs.iloc[-1].distance_outside == pytest.approx(1.98)
    assert pairs.iloc[-1].scaled_residual == pytest.approx(-100)
    assert result.table("expiries").fitted_discount.iloc[0] == 1.02
    assert result.table("expiries").fitted_forward.iloc[0] == pytest.approx(102)


@pytest.mark.parametrize("strikes", [(100.0,), (100.0, 100.0 + 1e-10)])
def test_sparse_or_nearly_coincident_strikes_do_not_identify_discount(strikes):
    frame, time, config = fixture(strikes)
    result = report(frame, time, config, refit=True)
    assert result.table("expiries").refit_reason.iloc[0] == "discount_unidentified"
    anchored = report(frame, time, config, refit=True, discount_anchor=1.02)
    assert anchored.table("expiries").refit_status.iloc[0] == "pass"


def test_ambiguous_unmatched_crossed_and_asynchronous_legs_are_not_fitted():
    frame, time, config = fixture()
    frame.loc[frame.index[1], "exchange_time"] -= pd.Timedelta(seconds=1)
    frame.loc[frame.index[2], "bid_price"] = 1e6
    frame = pd.concat([frame, frame.iloc[[4]]], ignore_index=True)
    frame = frame.drop(index=7)
    result = report(frame, time, config, refit=True)
    reasons = set(result.table("pairs").reason)
    assert {"unmatched_strike", "invalid_quote_leg", "duplicate_pair_legs"}.issubset(reasons)
    assert result.table("expiries").n_eligible.sum() == 1


def test_unverified_payoff_and_mismatched_forward_are_not_validated():
    frame, time, config = fixture()
    inverse = report(frame, time, replace(config, payoff="inverse"), refit=True)
    assert inverse.table("pairs").status.eq("not_applicable").all()
    frame.loc[frame.index[0], "forward_price"] += 1
    result = report(frame, time, config)
    assert result.table("pairs").reason.iloc[0] == "inconsistent_declared_forward_or_discount"
    with pytest.raises(ValueError, match="bounds"):
        report(frame, time, config, discount_anchor=1.02, discount_bounds=(None, 1))


@pytest.mark.parametrize("time_shift", [0, 1, -10000000])
def test_parity_deserializes_input_a_constant_number_of_times(monkeypatch, time_shift):
    """Large immutable reports must not be parsed again for every strike pair."""
    from option_chain_analytics.diagnostics import QuoteDiagnosticReport

    frame, time, config = fixture()
    requested = time - pd.Timedelta(seconds=time_shift)
    quality = diagnose_quotes(frame, config=config, requested_time=requested,
                              source_time=min(time, requested))
    expected = diagnose_parity(quality, spread_floor=0.005).to_dict()
    deserialize = QuoteDiagnosticReport.to_dict
    reads = []

    def counted(self):
        if self is quality:
            reads.append(1)
        return deserialize(self)

    monkeypatch.setattr(QuoteDiagnosticReport, "to_dict", counted)
    actual = diagnose_parity(quality, spread_floor=0.005).to_dict()
    assert actual == expected  # includes ordinary, future-observation and expired checks
    assert len(reads) <= 2  # one metadata snapshot and one quotes table
    pairs = QuoteDiagnosticReport.from_dict(actual).table("pairs")
    assert pairs.status.eq("pass" if time_shift == 0 else "not_checked").all()
    if time_shift:
        assert pairs.reason.eq("ineligible_observation_or_expiry_time").all()
