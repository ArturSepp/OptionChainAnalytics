"""Independent hand intervals and exact-inventory recovery without timestamp substitution."""

from copy import deepcopy
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from option_chain_analytics.diagnostics import (
    QuoteDiagnosticConfig, diagnose_quotes, diagnose_parity,
)


@pytest.fixture(scope="module")
def research():
    path = Path(__file__).resolve().parents[1] / "examples/parity_attribution.py"
    if not path.is_file():
        pytest.skip("Parity attribution is repository-only")
    spec = importlib.util.spec_from_file_location("parity_attribution", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def raw():
    when = pd.Timestamp("2024-04-10T12:00:00Z")
    return pd.DataFrame([dict(contract=cp, underlying_index="BTC", mat_id="test", strike=100., optiontype=cp,
        exchange_time=when-pd.Timedelta(seconds=10), expiry=pd.Timestamp("2024-10-01T08:00:00Z"),
        forward_price=100., discount=1., ttm=.5, bid_price=9., ask_price=11., bid_iv=.19, ask_iv=.21,
        bid_size=1., ask_size=1., open_interest=1., delta=.5, usd_multiplier=1., contract_size=1.) for cp in ("C", "P")])


def reports(raw, when="2024-04-10T12:00:00Z"):
    time = pd.Timestamp(when)
    q = diagnose_quotes(raw, config=QuoteDiagnosticConfig("USD per unit", payoff="standard_european", settlement="cash"),
        requested_time=time, source_time=time, source_row_ids=raw.contract.tolist())
    return q, diagnose_parity(q, spread_floor=.01)


def run(research, q, p, selected=("C",), **kwargs):
    return research.attribute_parity(q, p, list(selected), group_id="test", split_utc="2024-04-22T00:00:00Z", **kwargs)


def context(raw, source_forward=100.):
    rows = []
    for r in raw.to_dict("records"):
        rows.append(dict(source_row_id=r["contract"], contract=r["contract"], underlying_index=r["underlying_index"],
            mat_id=r["mat_id"], strike=r["strike"], optiontype=r["optiontype"], expiry=r["expiry"],
            requested_time=pd.Timestamp("2024-04-10T12:00:00Z"), event_time=r["exchange_time"],
            common_forward=r["forward_price"], source_forward=source_forward,
            native_bid=r["bid_price"]/r["forward_price"], native_ask=r["ask_price"]/r["forward_price"],
            common_anchor_time=r["exchange_time"]+pd.Timedelta(seconds=2)))
    return dict(mapping="inverse_forward_value_D1", rows=rows)


def test_existing_exact_pair_pass_has_stable_identity_and_no_recovery(research, raw):
    q, p = reports(raw)
    result = run(research, q, p, ("C", "P"))
    rows, summary = result.table("quotes"), result.table("summary").iloc[0]
    assert rows.attribution.tolist() == ["exact_pair_pass", "exact_pair_pass"]
    assert rows.recoverability.eq("already_supported").all()
    assert rows.pair_id.nunique() == 1 and summary.recoverable_selected_quotes == 0
    assert summary.original_status == summary.recomputed_status == "pass"
    reordered = run(research, *reports(raw.iloc[::-1]), ("P", "C"))
    assert set(reordered.table("quotes").pair_id) == set(rows.pair_id)


def test_omitted_pair_is_recoverable_only_from_original_exact_inventory(research, raw):
    q, p = reports(raw)
    old = p.to_dict()
    old["tables"]["pairs"]["data"] = []
    result = run(research, q, old, ("C", "P"))
    rows, summary = result.table("quotes"), result.table("summary").iloc[0]
    assert rows.recoverability.eq("recoverable_original_exact_evidence").all()
    assert summary.original_status == "unavailable" and summary.recomputed_status == "pass"
    assert summary.recoverable_selected_quotes == 2
    assert len(result.metadata["recomputed_parity"]["tables"]["pairs"]["data"]) == 1
    assert old["tables"]["pairs"]["data"] == []


def test_different_times_never_become_recovered_pairs(research, raw):
    raw.loc[1, "exchange_time"] -= pd.Timedelta(seconds=1)
    result = run(research, *reports(raw), ("C", "P"))
    rows = result.table("quotes")
    assert rows.attribution.eq("opposite_leg_at_different_event_time").all()
    assert rows.recomputed_status.eq("unavailable").all()
    assert rows.minimum_observed_event_gap_seconds.eq(1.).all()
    assert rows.exact_opposite_source_ids.tolist() == [[], []]
    assert result.table("summary").iloc[0].recoverable_selected_quotes == 0


def test_absent_opposite_leg_and_empty_selection_never_pass(research, raw):
    q, p = reports(raw.iloc[:1])
    row = run(research, q, p).table("quotes").iloc[0]
    assert row.attribution == "opposite_leg_absent" and row.recomputed_status == "unavailable"
    summary = run(research, q, p, ()).table("summary").iloc[0]
    assert summary.selected_rows == 0 and summary.recomputed_status == "unavailable"


def test_duplicate_exact_legs_are_reported_without_choosing_a_winner(research, raw):
    raw = pd.concat([raw, raw.iloc[1:].assign(contract="P2")], ignore_index=True)
    row = run(research, *reports(raw)).table("quotes").iloc[0]
    assert row.attribution == "ambiguous_exact_pair_legs"
    assert row.exact_opposite_source_ids == ["P", "P2"] and row.recomputed_status == "unavailable"


@pytest.mark.parametrize("defect,reason", [("missing", "selected_event_clock_unavailable"),
    ("future", "future_selected_event"), ("opposite_future", "opposite_leg_only_future"),
    ("expiry", "expired_selected_quote"), ("invalid_price", "invalid_quote_leg"),
    ("identity", "missing_or_unsupported_pair_identity")])
def test_blocking_evidence_is_never_a_pass(research, raw, defect, reason):
    if defect == "missing":
        raw.loc[0, "exchange_time"] = None
    elif defect == "future":
        raw.loc[0, "exchange_time"] = pd.Timestamp("2024-04-10T12:00:01Z")
    elif defect == "opposite_future":
        raw.loc[1, "exchange_time"] = pd.Timestamp("2024-04-10T12:00:01Z")
    elif defect == "expiry":
        raw["expiry"] = pd.Timestamp("2024-04-10T12:00:00Z")
    elif defect == "invalid_price":
        raw.loc[1, "bid_price"] = 12.
    else:
        raw["underlying_index"] = None
    row = run(research, *reports(raw)).table("quotes").iloc[0]
    assert row.attribution == reason and row.recomputed_status != "pass"


def test_hand_common_failure_local_pass_never_qualifies_common_surface(research, raw):
    raw.loc[0, ["bid_price", "ask_price"]] = [20., 22.]
    raw.loc[1, ["bid_price", "ask_price"]] = [3., 5.]
    result = run(research, *reports(raw), ("C", "P"), context=context(raw, 120.))
    pair, summary = result.table("pairs").iloc[0], result.table("summary").iloc[0]
    assert pair.common_status == "fail" and pair.common_lower == 15. and pair.common_upper == 19.
    assert pair.common_declared_parity == 0. and pair.common_distance_outside == 15.
    assert pair.local_status == "pass" and pair.local_lower == pytest.approx(18.)
    assert pair.local_upper == pytest.approx(22.8) and pair.local_declared_parity == 20.
    assert pair.common_forward == 100. and pair.source_forward == 120.
    assert pair.anchor_minus_pair_seconds == 2. and pair.common_fail_local_pass
    assert summary.recomputed_status == "fail" and summary.recoverable_selected_quotes == 0
    assert result.table("quotes").recoverability.eq("observed_common_failure_retained").all()


@pytest.mark.parametrize("defect,reason", [("missing", "source_forward_unavailable"),
    ("incoherent", "incoherent_source_forwards"), ("absent", "original_context_missing")])
def test_unavailable_source_forwards_do_not_produce_local_passes(research, raw, defect, reason):
    ctx = context(raw)
    if defect == "missing":
        ctx["rows"][1]["source_forward"] = None
    elif defect == "incoherent":
        ctx["rows"][1]["source_forward"] = 101.
    else:
        del ctx["rows"][1]
    result = run(research, *reports(raw), context=ctx)
    pair = result.table("pairs").iloc[0]
    assert pair.local_status == "unavailable" and pair.local_reason == reason
    assert result.table("summary").iloc[0].recomputed_status == "pass"


def test_missing_common_coordinates_retain_original_context_without_a_pass(research, raw):
    ctx = context(raw)
    raw[["forward_price", "bid_price", "ask_price"]] = float("nan")
    for row in ctx["rows"]:
        row["common_forward"] = None
    result = run(research, *reports(raw), context=ctx)
    assert result.table("pairs").local_status.eq("unavailable").all()
    assert result.table("summary").iloc[0].recomputed_status == "unavailable"


@pytest.mark.parametrize("defect", ["units", "clock", "identity", "premium", "anchor", "mapping"])
def test_original_context_provenance_is_enforced(research, raw, defect):
    ctx = context(raw)
    row = ctx["rows"][0]
    if defect == "units":
        row["common_forward"] = 1.
    elif defect == "clock":
        row["event_time"] -= pd.Timedelta(seconds=1)
    elif defect == "identity":
        row["strike"] = 101.
    elif defect == "premium":
        row["native_bid"] *= 100.
    elif defect == "anchor":
        row["common_anchor_time"] = pd.Timestamp("2024-04-10T12:00:01Z")
    else:
        ctx["mapping"] = "implicit"
    with pytest.raises(ValueError):
        run(research, *reports(raw), context=ctx)


def test_stale_reported_pass_can_become_a_failure_and_is_retained(research, raw):
    raw.loc[0, "bid_price"], raw.loc[0, "ask_price"] = 20., 22.
    q, p = reports(raw)
    old = p.to_dict()
    i = old["tables"]["pairs"]["columns"].index("status")
    old["tables"]["pairs"]["data"][0][i] = "pass"
    result = run(research, q, old)
    row = result.table("quotes").iloc[0]
    assert row.original_status == "pass" and row.recomputed_status == "fail"
    assert row.recoverability == "original_checked_result_not_reproduced"


def test_reports_are_immutable_and_validation_cannot_change_calibration(research, raw):
    q, p = reports(raw)
    original = deepcopy((q.to_dict(), p.to_dict()))
    before = run(research, q, p)
    validation = raw.copy()
    validation["exchange_time"] = pd.Timestamp("2024-04-23T11:59:50Z")
    validation.loc[0, "bid_price"], validation.loc[0, "ask_price"] = 20., 22.
    vq, vp = reports(validation, "2024-04-23T12:00:00Z")
    changed = run(research, vq, vp)
    assert changed.table("summary").iloc[0].split == "validation"
    assert run(research, q, p).to_dict() == before.to_dict()
    assert (q.to_dict(), p.to_dict()) == original
    altered = before.table("quotes")
    altered.loc[0, "recomputed_status"] = "fail"
    assert before.table("quotes").iloc[0].recomputed_status == "pass"


def test_missing_selected_or_mismatched_sidecars_are_rejected(research, raw):
    q, p = reports(raw)
    with pytest.raises(ValueError, match="identity"):
        run(research, q, p, ("absent",))
    old = p.to_dict()
    old["metadata"]["requested_time"] = "2024-04-11T12:00:00Z"
    with pytest.raises(ValueError, match="provenance"):
        run(research, q, old)
    old = p.to_dict()
    old["tables"]["pairs"]["data"][0][0] = "other_underlying"
    with pytest.raises(ValueError, match="source observations"):
        run(research, q, old)
