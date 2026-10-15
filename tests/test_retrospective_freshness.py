"""Hand timing ranks, frozen cohorts and unchanged exact source-pair requirements."""

from copy import deepcopy
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from option_chain_analytics.diagnostics import QuoteDiagnosticConfig, diagnose_quotes, diagnose_parity


@pytest.fixture(scope="module")
def research():
    path = Path(__file__).resolve().parents[1] / "examples/retrospective_freshness.py"
    if not path.is_file():
        pytest.skip("Event policy example is repository-only")
    spec = importlib.util.spec_from_file_location("retrospective_freshness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def inventory():
    when = pd.Timestamp("2024-04-10T12:00:00Z")
    rows = []
    for strike, age in ((100., 10), (110., 30)):
        for cp in ("C", "P"):
            low = 9. if strike == 100 else 1. if cp == "C" else 11.
            sid = f"{cp}:{strike}"
            rows.append(dict(group_id="g0", source_row_id=sid, contract=sid, strike=strike, optiontype=cp,
                requested_time=when, event_time=when-pd.Timedelta(seconds=age), exchange_time=when-pd.Timedelta(seconds=age),
                expiry=pd.Timestamp("2024-10-01T08:00:00Z"), underlying_index="BTC", mat_id="test",
                forward_price=100., discount=1., ttm=.5, bid_price=low, ask_price=low+2,
                bid_iv=.19, ask_iv=.21, bid_size=1., ask_size=1., open_interest=1., delta=.5,
                usd_multiplier=1., contract_size=1.))
    return pd.DataFrame(rows)


def fit(research, inventory, **kwargs):
    return research.fit_event_policy(inventory, split_utc="2024-04-22T00:00:00Z", **kwargs)


def sidecars(inventory):
    config = QuoteDiagnosticConfig("USD per unit", payoff="standard_european", settlement="cash")
    time = inventory.requested_time.iloc[0]
    q = diagnose_quotes(inventory, config=config, requested_time=time, source_time=time,
                        source_row_ids=inventory.source_row_id.tolist())
    return q, diagnose_parity(q, spread_floor=.01)


def test_hand_nearest_rank_budgets_and_inclusive_boundaries(research, inventory):
    policy = fit(research, inventory, quantile=.5)
    assert policy["budgets"] == dict(quote_age_seconds=10., anchor_age_seconds=10., asynchrony_seconds=20.)
    report = research.apply_event_policy(inventory, policy)
    rows, group = report.table("rows"), report.table("groups").iloc[0]
    assert rows.event_age_status.tolist() == ["pass", "fail", "pass", "fail"]
    assert group.anchor_age_status == group.asynchrony_status == "pass"
    assert group.status == "fail"
    assert group.latest_event_anchor == "2024-04-10T11:59:50+00:00"


def test_age_cap_and_complete_group_denominators(research, inventory):
    policy = fit(research, inventory, cap_seconds=15.)
    assert policy["budgets"] == dict(quote_age_seconds=15., anchor_age_seconds=10., asynchrony_seconds=15.)
    assert policy["calibration_rows"] == policy["eligible_age_rows"] == 4
    assert policy["calibration_groups"] == policy["complete_clock_groups"] == 1


def test_training_is_permutation_invariant_and_validation_is_rejected(research, inventory):
    expected = fit(research, inventory)
    assert fit(research, inventory.iloc[::-1]) == expected
    validation = inventory.copy()
    validation["requested_time"] = pd.Timestamp("2024-04-22T00:00:00Z")
    with pytest.raises(ValueError, match="calibration-only"):
        fit(research, pd.concat([inventory, validation.assign(group_id="v")]))
    assert fit(research, inventory) == expected


def test_validation_changes_cannot_change_policy_or_calibration_assessments(research, inventory):
    policy = fit(research, inventory)
    validation = inventory.assign(group_id="v", requested_time=pd.Timestamp("2024-04-23T12:00:00Z"),
                                  event_time=pd.Timestamp("2024-04-23T11:59:50Z"))
    before = research.apply_event_policy(pd.concat([inventory, validation]), policy)
    validation["event_time"] = pd.Timestamp("2025-01-01T00:00:00Z")
    after = research.apply_event_policy(pd.concat([inventory, validation]), policy)
    for table in ("rows", "groups"):
        a, b = before.table(table), after.table(table)
        pd.testing.assert_frame_equal(a[a.split.eq("calibration")].reset_index(drop=True),
                                      b[b.split.eq("calibration")].reset_index(drop=True))
    assert policy == fit(research, inventory)


@pytest.mark.parametrize("clock", [None, "2024-04-10T11:59:55", "invalid"])
def test_missing_or_naive_event_clocks_never_pass(research, inventory, clock):
    policy = fit(research, inventory)
    inventory["event_time"] = inventory.event_time.astype(object)
    inventory.loc[0, "event_time"] = clock
    report = research.apply_event_policy(inventory, policy)
    assert report.table("rows").iloc[0].event_age_status == "unavailable"
    assert report.table("groups").iloc[0].status == "unavailable"


def test_known_failures_dominate_incomplete_timing(research, inventory):
    policy = fit(research, inventory)
    inventory["event_time"] = inventory.event_time.astype(object)
    inventory.loc[0, "event_time"] = None
    inventory.loc[1, "event_time"] = pd.Timestamp("2024-04-10T12:00:01Z")
    result = research.apply_event_policy(inventory, policy).table("groups").iloc[0]
    assert result.status == "fail" and result.n_missing_clocks == result.n_future_events == 1
    assert "future_event" in result.reasons
    rows = research.apply_event_policy(inventory, policy).table("rows").set_index("source_row_id")
    assert rows.loc[inventory.source_row_id.iloc[1], "event_age_status"] == "fail"


def test_incomplete_clocks_cannot_prove_the_youngest_event_is_stale(research, inventory):
    policy = fit(research, inventory)
    inventory["event_time"] = (inventory.requested_time-pd.Timedelta(seconds=15)).astype(object)
    inventory.loc[0, "event_time"] = None
    result = research.apply_event_policy(inventory, policy).table("groups").iloc[0]
    assert result.anchor_age_seconds == 15.
    assert result.anchor_age_status == "unavailable"
    assert result.status == "unavailable"


def test_known_excessive_time_range_still_fails_with_a_missing_clock(research, inventory):
    policy = fit(research, inventory)
    inventory["event_time"] = inventory.event_time.astype(object)
    inventory.loc[0, "event_time"] = None
    inventory.loc[1, "event_time"] = inventory.requested_time.iloc[1]-pd.Timedelta(seconds=100)
    result = research.apply_event_policy(inventory, policy).table("groups").iloc[0]
    assert result.asynchrony_status == "fail"
    assert result.status == "fail"


def test_expiry_cannot_become_a_fresh_observation(research, inventory):
    policy = fit(research, inventory)
    inventory["expiry"] = inventory.requested_time
    report = research.apply_event_policy(inventory, policy)
    assert report.table("rows").event_age_status.eq("not_applicable").all()
    assert report.table("groups").iloc[0].status == "not_applicable"


def test_no_calibratable_clocks_produce_unavailable_budgets(research, inventory):
    inventory["event_time"] = None
    policy = fit(research, inventory)
    assert set(policy["budgets"].values()) == {None}
    assert policy["eligible_age_rows"] == policy["complete_clock_groups"] == 0
    assert research.apply_event_policy(inventory, policy).table("groups").iloc[0].status == "unavailable"


@pytest.mark.parametrize("defect", ["duplicate", "mixed_time", "mixed_expiry", "naive_request", "naive_expiry"])
def test_invalid_inventory_identity_is_rejected(research, inventory, defect):
    if defect == "duplicate":
        inventory = pd.concat([inventory, inventory.iloc[:1]])
    elif defect == "mixed_time":
        inventory.loc[0, "requested_time"] += pd.Timedelta(seconds=1)
    elif defect == "mixed_expiry":
        inventory.loc[0, "expiry"] += pd.Timedelta(seconds=1)
    else:
        column = "requested_time" if defect == "naive_request" else "expiry"
        inventory[column] = inventory[column].astype(object)
        inventory.loc[0, column] = "2024-04-10"
    with pytest.raises(ValueError):
        fit(research, inventory)


@pytest.mark.parametrize("kwargs", [dict(quantile=0), dict(quantile=1.1), dict(quantile=True),
                                    dict(cap_seconds=-1), dict(cap_seconds=float("inf"))])
def test_invalid_policy_settings_are_rejected(research, inventory, kwargs):
    with pytest.raises(ValueError):
        fit(research, inventory, **kwargs)


def test_frozen_policy_tampering_and_mutable_results(research, inventory):
    policy = fit(research, inventory)
    report = research.apply_event_policy(inventory, policy)
    before = report.to_dict()
    policy["budgets"]["quote_age_seconds"] = 999.
    with pytest.raises(ValueError, match="artifact"):
        research.apply_event_policy(inventory, policy)
    inventory.loc[0, "event_time"] = None
    copy = report.table("rows")
    copy.loc[0, "event_age_status"] = "pass"
    assert report.to_dict() == before
    assert before["metadata"]["receive_availability_verified"] is False
    assert before["metadata"]["strict_snapshot_age_verified"] is False


def test_selected_event_evidence_is_separate_from_original_snapshot_quality(research, inventory):
    policy = fit(research, inventory)
    q, p = sidecars(inventory)
    original = deepcopy((q.to_dict(), p.to_dict()))
    result = research.selected_qualification(q, p, inventory, inventory.source_row_id.tolist(), policy)
    assert result["original_quality"] == "unavailable"
    assert result["event_quality"] == result["exact_parity"] == "pass"
    assert (q.to_dict(), p.to_dict()) == original


def test_bounded_asynchrony_does_not_synchronize_parity_legs(research, inventory):
    policy = fit(research, inventory)
    inventory.loc[0, "event_time"] += pd.Timedelta(seconds=1)
    inventory["exchange_time"] = inventory.event_time
    q, p = sidecars(inventory)
    result = research.selected_qualification(q, p, inventory, inventory.source_row_id.tolist(), policy)
    assert result["exact_parity"] == "unavailable"
    assert p.table("pairs").query('strike == 100').status.eq("not_checked").all()


def test_unknown_selection_and_clock_mismatch_are_rejected(research, inventory):
    policy = fit(research, inventory)
    q, p = sidecars(inventory)
    with pytest.raises(ValueError, match="identity"):
        research.selected_qualification(q, p, inventory, ["absent"], policy)
    inventory.loc[0, "event_time"] += pd.Timedelta(seconds=1)
    with pytest.raises(ValueError, match="differs"):
        research.selected_qualification(q, p, inventory, inventory.source_row_id.tolist(), policy)
    assert research.selected_qualification(q, p, inventory, [], policy)["event_quality"] == "unavailable"
