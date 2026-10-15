"""Repository-only event-cadence policy; historical receipt availability stays unknown."""

from enum import Enum
from hashlib import sha256
import json
from math import ceil
from numbers import Real

import numpy as np
import pandas as pd

from option_chain_analytics import generate_simulated_options_data
from option_chain_analytics.diagnostics import QuoteDiagnosticReport


FORMAT = "oca-retrospective-event-policy-v1"
REQUIRED = {"strike", "forward_price", "discount", "ttm", "optiontype", "two_sided_price",
            "nonnegative_price", "uncrossed_price", "iv", "exchange_time", "expiry", "price_bounds", "quote_age"}
FIELDS = ("group_id", "source_row_id", "contract", "requested_time", "expiry", "event_time", "strike", "optiontype")
BUDGETS = ("quote_age_seconds", "anchor_age_seconds", "asynchrony_seconds")


def _aware(value):
    time = pd.Timestamp(value)
    if pd.isna(time) or time.tzinfo is None:
        raise ValueError("A valid timezone-aware timestamp is required")
    return time.tz_convert("UTC")


def _event(value):
    try:
        return _aware(value), ""
    except (TypeError, ValueError):
        return None, "missing_or_invalid_event_clock"


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _inventory(inventory):
    frame = pd.DataFrame(inventory, columns=FIELDS).copy()
    for name in ("group_id", "source_row_id", "contract"):
        if any(not isinstance(v, str) or not v for v in frame[name]):
            raise ValueError("Group, row and contract identities must be explicit")
    if frame.duplicated(["group_id", "source_row_id"]).any() or frame.duplicated(["group_id", "contract"]).any():
        raise ValueError("Duplicate inventory identity")
    frame["requested_time"] = frame.requested_time.map(lambda v: _aware(v).isoformat())
    frame["expiry"] = frame.expiry.map(lambda v: _aware(v).isoformat())
    clocks = [_event(v) for v in frame.event_time]
    frame["event_time"] = [t.isoformat() if t is not None else None for t, _ in clocks]
    frame["clock_reason"] = [r for _, r in clocks]
    frame["event_age_seconds"] = [(None if t is None else (_aware(r)-t).total_seconds())
                                  for r, (t, _) in zip(frame.requested_time, clocks)]
    frame["expired"] = [_aware(r) >= _aware(e) for r, e in zip(frame.requested_time, frame.expiry)]
    for _, group in frame.groupby("group_id", sort=True):
        if group.requested_time.nunique() != 1 or group.expiry.nunique() != 1:
            raise ValueError("An inventory group must have one requested time and actual expiry")
    return frame.sort_values(["group_id", "source_row_id"]).reset_index(drop=True)


def _rank(values, quantile, cap):
    values = sorted(values)
    return None if not values else float(min(values[ceil(quantile*len(values))-1], cap))


def fit_event_policy(calibration_inventory, *, split_utc, quantile=.95, cap_seconds=3600.):
    """Freeze descriptive nearest-rank budgets from calibration inventory only.

    All original inventory is the sampling unit, independently of model selections
    and diagnostic outcomes. Budgets describe event cadence; they do not identify an
    economically acceptable age, a quote-update time or collector receipt latency.
    """
    for value, name in ((quantile, "quantile"), (cap_seconds, "cap_seconds")):
        if isinstance(value, bool) or not isinstance(value, Real) or not np.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    if quantile > 1:
        raise ValueError("quantile must not exceed one")
    split = _aware(split_utc)
    frame = _inventory(calibration_inventory)
    if frame.empty or any(_aware(t) >= split for t in frame.requested_time):
        raise ValueError("Policy fitting requires nonempty calibration-only inventory")
    valid = ~frame.expired & frame.event_age_seconds.notna() & frame.event_age_seconds.ge(0)
    anchors, skews = [], []
    for _, group in frame.groupby("group_id", sort=True):
        ages = group.event_age_seconds
        if not group.expired.any() and ages.notna().all() and ages.ge(0).all():
            anchors.append(float(ages.min()))
            skews.append(float(ages.max()-ages.min()))
    # Only timing identities enter the training fingerprint; no prices or fitted results.
    projection = json.loads(frame.to_json(orient="records"))
    result = dict(format=FORMAT, split_utc=split.isoformat(), quantile=float(quantile),
        cap_seconds=float(cap_seconds), method="nearest-rank, capped; calibration inventory only",
        budgets=dict(zip(BUDGETS, (_rank(frame.loc[valid, "event_age_seconds"], quantile, cap_seconds),
                                  _rank(anchors, quantile, cap_seconds), _rank(skews, quantile, cap_seconds)))),
        calibration_rows=len(frame), eligible_age_rows=int(valid.sum()), calibration_groups=frame.group_id.nunique(),
        complete_clock_groups=len(anchors), calibration_inventory_sha256=_digest(projection),
        clock_scope="provider event cadence; no quote-update or receipt-time assertion",
        parity_rule="exact original event timestamps; bounded asynchrony never synchronizes legs",
        receive_availability_verified=False, economic_freshness_validated=False)
    result["policy_sha256"] = _digest(result)
    return result


def _policy(policy):
    result = json.loads(json.dumps(policy, allow_nan=False))
    digest = result.pop("policy_sha256")
    if (result.get("format") != FORMAT or _digest(result) != digest
            or result.get("receive_availability_verified") is not False
            or result.get("economic_freshness_validated") is not False):
        raise ValueError("Invalid frozen event-policy artifact")
    _aware(result["split_utc"])
    for name in BUDGETS:
        value = result["budgets"][name]
        if value is not None and (isinstance(value, bool) or not isinstance(value, Real)
                                  or not np.isfinite(value) or not 0 <= value <= result["cap_seconds"]):
            raise ValueError("Invalid event-policy budget")
    return result


def _status(states):
    states = list(states)
    if "fail" in states:
        return "fail"
    if not states or "unavailable" in states:
        return "unavailable"
    return "not_applicable" if all(s == "not_applicable" for s in states) else "pass"


def _timing(group, budgets):
    ages = group.event_age_seconds
    expired = bool(group.expired.all())
    complete = ages.notna().all() and ages.ge(0).all()
    valid = ages[ages.notna() & ages.ge(0)]
    anchor, skew = (float(valid.min()), float(valid.max()-valid.min())) if len(valid) else (None, None)
    reasons, states = [], {}
    for name, value in (("anchor_age_seconds", anchor), ("asynchrony_seconds", skew)):
        limit = budgets[name]
        state = ("not_applicable" if expired else "fail" if ages.lt(0).any() else
                 "unavailable" if name == "anchor_age_seconds" and not complete else
                 "fail" if value is not None and limit is not None and value > limit else
                 "unavailable" if not complete or limit is None else "pass")
        states[name.removesuffix("_seconds")+"_status"] = state
        if state not in ("pass", "not_applicable"):
            reasons.append(name+":"+state)
    rows = []
    for row in group.to_dict("records"):
        age, limit = row["event_age_seconds"], budgets["quote_age_seconds"]
        state = ("not_applicable" if row["expired"] else "unavailable" if pd.isna(age) else
                 "fail" if age < 0 else "unavailable" if limit is None else "pass" if age <= limit else "fail")
        reason = ("expired" if row["expired"] else row["clock_reason"] if pd.isna(age) else
                  "future_event" if age < 0 else "age_budget_unavailable" if limit is None else
                  "event_age_exceeds_budget" if state == "fail" else "")
        rows.append(dict(row, event_age_status=state, event_age_reason=reason))
    states["quote_age_status"] = _status(r["event_age_status"] for r in rows)
    reasons.extend(r["event_age_reason"] for r in rows if r["event_age_reason"])
    clocks = [r["event_time"] for r in rows if r["event_time"] is not None and not r["expired"]
              and r["event_age_seconds"] >= 0]
    return rows, dict(group_id=group.group_id.iloc[0], requested_time=group.requested_time.iloc[0],
        expiry=group.expiry.iloc[0], n_rows=len(group), n_missing_clocks=int(ages.isna().sum()),
        n_future_events=int(ages.lt(0).sum()), latest_event_anchor=max(clocks) if clocks else None,
        anchor_age_seconds=anchor, asynchrony_seconds=skew, **states,
        status=_status(states.values()), reasons=sorted(set(reasons)))


def apply_event_policy(inventory, policy):
    """Assess unchanged inventory under a frozen policy, retaining every row and unknown."""
    frozen = _policy(policy)
    frame = _inventory(inventory)
    rows, groups = [], []
    for _, group in frame.groupby("group_id", sort=True):
        local, result = _timing(group, frozen["budgets"])
        result["split"] = "calibration" if _aware(result["requested_time"]) < _aware(frozen["split_utc"]) else "validation"
        rows.extend(dict(r, split=result["split"]) for r in local)
        groups.append(result)
    return QuoteDiagnosticReport.from_tables(dict(rows=pd.DataFrame(rows), groups=pd.DataFrame(groups)),
        dict(kind="retrospective_event_timing", policy=policy, strict_snapshot_age_verified=False,
             receive_availability_verified=False, receipt_times_inferred=False))


def selected_qualification(quality, parity, inventory, selected_ids, policy):
    """Compare original quality with explicitly conditional selected-row event quality.

    Original snapshot age and exact-time parity remain intact. This is an OCA evidence
    report, not permission to bypass a downstream model's existing qualification gate.
    """
    _policy(policy)
    if not selected_ids:
        return dict(original_quality="unavailable", event_quality="unavailable", exact_parity="unavailable",
                    timing="unavailable", reasons=["empty_selection"])
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("Selected source identities must be unique")
    qm, pm = quality.metadata, parity.metadata
    if (qm.get("kind") != "quote_quality" or pm.get("kind") != "parity"
            or qm["config"] != pm["config"] or qm["requested_time"] != pm["requested_time"]
            or qm.get("source_time") != pm.get("source_time")):
        raise ValueError("Quote/parity provenance mismatch")
    frame = _inventory(inventory)
    quotes = quality.table("quotes").set_index("source_row_id")
    if (not quotes.index.is_unique or not set(selected_ids).issubset(quotes.index)
            or not set(selected_ids).issubset(frame.source_row_id)):
        raise ValueError("Selected source identity is absent or ambiguous")
    local = frame.set_index("source_row_id").loc[selected_ids].reset_index()
    if local.group_id.nunique() != 1:
        raise ValueError("Select one actual expiry/snapshot group")
    for row in local.to_dict("records"):
        source = quotes.loc[row["source_row_id"]]
        if (row["contract"] != source.contract or row["strike"] != source.strike
                or row["optiontype"] != source.optiontype or _aware(row["expiry"]) != _aware(source.expiry)
                or _event(row["event_time"])[0] != _event(source.exchange_time)[0]
                or _aware(row["requested_time"]) != _aware(qm["requested_time"])):
            raise ValueError("Timing inventory differs from original quote evidence")
    checks = quality.table("checks")
    checks = checks[checks.source_row_id.isin(selected_ids)]
    if checks.duplicated(["source_row_id", "check"]).any():
        raise ValueError("Duplicate quote-check identity")
    failures = checks.loc[checks.status.eq("fail"), "reason"].tolist()
    missing = []
    for sid in selected_ids:
        observed = checks[checks.source_row_id.eq(sid)].set_index("check")
        missing.extend(name for name in REQUIRED if name not in observed.index
                       or observed.loc[name, "status"] not in ("pass", "fail"))
    snapshot = quality.table("summary").iloc[0].snapshot_age_status
    original = "fail" if failures or snapshot == "fail" else (
        "unavailable" if missing or snapshot != "pass" or qm.get("source_time") is None else "pass")
    nonage_failures = checks.loc[checks.status.eq("fail") & checks.check.ne("quote_age"), "reason"].tolist()
    nonage = "fail" if nonage_failures else "unavailable" if set(missing)-{"quote_age"} else "pass"
    _, timing = _timing(local, policy["budgets"])
    pairs = parity.table("pairs")
    pairs = pairs[pairs.source_row_ids.map(lambda ids: bool(set(ids).intersection(selected_ids)))]
    seen, pair_states = set(), []
    for pair in pairs.to_dict("records"):
        ids = pair["source_row_ids"]
        if len(set(ids)) != len(ids) or not set(ids).issubset(quotes.index):
            raise ValueError("Parity source identity mismatch")
        legs = quotes.loc[ids]
        if pair["status"] in ("pass", "fail") and (len(ids) != 2 or set(legs.optiontype) != {"C", "P"}):
            raise ValueError("Checked parity needs one call and put")
        for name in ("strike", "expiry", "exchange_time", "mat_id", "underlying_index"):
            if legs[name].nunique(dropna=False) != 1 or pair[name] != legs[name].iloc[0]:
                raise ValueError("Parity must retain exact original source pairing")
        matched = set(ids).intersection(selected_ids)
        if seen.intersection(matched):
            raise ValueError("Ambiguous selected parity coverage")
        seen.update(matched)
        pair_states.append(pair["status"] if pair["status"] in ("pass", "fail") else "unavailable")
    if seen != set(selected_ids):
        pair_states.append("unavailable")
    return dict(original_quality=original, event_quality=_status([nonage, timing["status"]]),
                exact_parity=_status(pair_states), timing=timing["status"],
                reasons=sorted(set(nonage_failures + ["unchecked:"+m for m in missing if m != "quote_age"]
                                   + timing["reasons"])), timing_details=timing)


class Locals(Enum):
    """Offline synthetic inventory demonstration."""

    SYNTHETIC = 1


def run_local(local: Locals = Locals.SYNTHETIC):
    """Print a deterministic cadence policy and assessment without writing market data."""
    if local != Locals.SYNTHETIC:
        raise ValueError("Unknown example")
    data = generate_simulated_options_data()
    time = data.get_timeindex()[0]
    frame = data.chain_ts[data.chain_ts.exchange_time.eq(time)].copy()
    frame["group_id"] = frame.expiry.map(str)
    frame["source_row_id"] = [f"synthetic:{i}" for i in range(len(frame))]
    frame["requested_time"], frame["event_time"] = time, frame.exchange_time
    policy = fit_event_policy(frame, split_utc=time+pd.Timedelta(days=1))
    print(json.dumps(policy, indent=2))
    print(apply_event_policy(frame, policy).table("groups").to_string(index=False))


if __name__ == "__main__":
    run_local(local=Locals.SYNTHETIC)
