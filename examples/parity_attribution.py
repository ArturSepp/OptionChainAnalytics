"""Repository-only parity attribution; original clocks, prices and gates remain explicit."""

from dataclasses import replace
from enum import Enum
from hashlib import sha256
import json

import numpy as np
import pandas as pd

from option_chain_analytics import generate_simulated_options_data
from option_chain_analytics.diagnostics import (
    QuoteDiagnosticConfig, QuoteDiagnosticReport, diagnose_quotes, diagnose_parity,
)


KEYS = ("underlying_index", "mat_id", "expiry", "strike", "exchange_time")


def _stamp(value):
    try:
        t = pd.Timestamp(value)
        return None if pd.isna(t) or t.tzinfo is None else t.tz_convert("UTC")
    except (TypeError, ValueError):
        return None


def _required_time(value):
    result = _stamp(value)
    if result is None:
        raise ValueError("A timezone-aware requested time and split are required")
    return result


def _restore(value):
    return value if isinstance(value, QuoteDiagnosticReport) else QuoteDiagnosticReport(
        json.dumps(value, sort_keys=True, allow_nan=False))


def _value(name, value):
    if name in ("exchange_time", "expiry"):
        t = _stamp(value)
        return t.isoformat() if t is not None else None
    return None if pd.isna(value) else value


def _scope(row):
    values = tuple(_value(k, row[k]) for k in KEYS[:-1])
    return None if any(v is None or str(v).strip() == "" for v in values) else values


def _state(value):
    return value if value in ("pass", "fail") else "unavailable"


def _aggregate(values):
    values = list(values)
    return "fail" if "fail" in values else "pass" if values and set(values) == {"pass"} else "unavailable"


def _members(pairs, quotes):
    result = {}
    for pair in pairs:
        ids = pair["source_row_ids"]
        if not ids or len(set(ids)) != len(ids) or not set(ids).issubset(quotes):
            raise ValueError("Invalid parity source identities")
        for key in KEYS:
            values = {_value(key, quotes[sid][key]) for sid in ids}
            if len(values) != 1 or _value(key, pair[key]) not in values:
                raise ValueError("Parity pair does not match original source observations")
        if pair["status"] in ("pass", "fail") and (
                len(ids) != 2 or {quotes[sid]["optiontype"] for sid in ids} != {"C", "P"}
                or any(_value(k, pair[k]) is None for k in KEYS)):
            raise ValueError("Checked parity must identify a complete exact call/put pair")
        for sid in ids:
            if sid in result:
                raise ValueError("Ambiguous reported pair membership")
            result[sid] = pair
    return result


def _context(context, quotes, requested):
    if context is None:
        return {}
    if context.get("mapping") != "inverse_forward_value_D1":
        raise ValueError("Original coin-to-forward-value mapping must be explicit")
    records = context["rows"]
    indexed = {r["source_row_id"]: r for r in records}
    if len(indexed) != len(records) or not set(indexed).issubset(quotes):
        raise ValueError("Ambiguous or unmatched original-forward context")
    for sid, row in indexed.items():
        q = quotes[sid]
        for name in ("contract", "underlying_index", "mat_id", "expiry", "strike", "optiontype"):
            if _value(name, row[name]) != _value(name, q[name]):
                raise ValueError("Original-forward context identity mismatch")
        if (_stamp(row["event_time"]) != _stamp(q["exchange_time"])
                or _required_time(row["requested_time"]) != requested):
            raise ValueError("Original-forward context clock mismatch")
        same_forward = (pd.isna(row["common_forward"]) and pd.isna(q["forward_price"])) or (
            row["common_forward"] == q["forward_price"])
        if not same_forward or q["discount"] != 1.:
            raise ValueError("Original-forward context differs from frozen common coordinates")
        anchor = _stamp(row.get("common_anchor_time"))
        if anchor is not None and anchor > requested:
            raise ValueError("Future common-forward anchor")
        for side in ("bid", "ask"):
            native, saved = row["native_"+side], q[side+"_price"]
            scaled = None if pd.isna(native) or pd.isna(row["common_forward"]) else row["common_forward"]*native
            if not (pd.isna(scaled) and pd.isna(saved)) and scaled != saved:
                raise ValueError("Original coin premium does not reproduce frozen quote")
    return indexed


def _local_pair(pair, quotes, context, config, requested, source, spread_floor):
    result = dict(local_status="unavailable", local_reason="no_checked_exact_pair",
        source_forward=None, common_forward=quotes[pair["source_row_ids"][0]]["forward_price"], forward_difference=None,
        anchor_minus_pair_seconds=None, local_lower=None, local_upper=None,
        local_declared_parity=None, local_distance_outside=None)
    if pair["status"] not in ("pass", "fail"):
        return result
    ids = pair["source_row_ids"]
    if not set(ids).issubset(context):
        return dict(result, local_reason="original_context_missing")
    rows = [context[sid] for sid in ids]
    forward = rows[0]["source_forward"]
    if any(r["source_forward"] is None or not np.isfinite(r["source_forward"])
           or r["source_forward"] <= 0 for r in rows):
        return dict(result, local_reason="source_forward_unavailable")
    if any(r["source_forward"] != forward for r in rows):
        return dict(result, local_reason="incoherent_source_forwards")
    raw = pd.DataFrame([quotes[sid] for sid in ids])
    raw["forward_price"], raw["discount"] = forward, 1.
    event = _required_time(pair["exchange_time"])
    raw["ttm"] = [(_required_time(r["expiry"])-event).total_seconds()/(365*86400) for r in rows]
    for side in ("bid", "ask"):
        raw[side+"_price"] = [forward*r["native_"+side] for r in rows]
        raw[side+"_iv"] = np.nan  # Common-coordinate IVs do not belong to a pair-local forward.
    local_config = replace(config, price_conversion="quoted")
    quality = diagnose_quotes(raw, config=local_config, requested_time=requested, source_time=source,
                              source_row_ids=ids)
    local = diagnose_parity(quality, spread_floor=spread_floor, refit=False,
        forward_source="unchanged coherent original pair-event provider forward",
        discount_source="validated inverse forward numeraire D=1").table("pairs").iloc[0]
    anchor = _stamp(rows[0].get("common_anchor_time"))
    common = quotes[ids[0]]["forward_price"]
    return dict(result, local_status=_state(local.status), local_reason=local.reason,
        source_forward=float(forward), common_forward=float(common), forward_difference=float(common-forward),
        anchor_minus_pair_seconds=(anchor-event).total_seconds() if anchor is not None else None,
        local_lower=local.lower, local_upper=local.upper, local_declared_parity=local.declared_parity,
        local_distance_outside=local.distance_outside)


def attribute_parity(quality, parity, selected_ids, *, group_id, split_utc, priority=False, context=None):
    """Trace selected evidence and recompute exact pairs from unchanged original inventory.

    Only a newly supported exact pair in the original common coordinates is a
    recoverable omission/result. A separate original-forward comparison never changes
    common-coordinate qualification. Missing receipt times remain unverified.
    """
    quality, parity = _restore(quality), _restore(parity)
    qm, pm = quality.metadata, parity.metadata
    requested, split = _required_time(qm["requested_time"]), _required_time(split_utc)
    if (qm.get("kind") != "quote_quality" or pm.get("kind") != "parity" or qm["config"] != pm["config"]
            or requested != _required_time(pm["requested_time"])
            or _stamp(qm.get("source_time")) != _stamp(pm.get("source_time"))):
        raise ValueError("Original quote/parity provenance differs")
    source = None if qm.get("source_time") is None else _required_time(qm["source_time"])
    if source is not None and source > requested:
        raise ValueError("Future source snapshot")
    records = quality.table("quotes").to_dict("records")
    quotes = {r["source_row_id"]: r for r in records}
    if len(quotes) != len(records) or len(set(selected_ids)) != len(selected_ids) or not set(selected_ids).issubset(quotes):
        raise ValueError("Ambiguous or missing selected source identity")
    if len({_value("expiry", r["expiry"]) for r in records}) > 1:
        raise ValueError("Attribute one actual expiry at a time")
    original = _members(parity.table("pairs").to_dict("records"), quotes)
    config = QuoteDiagnosticConfig(**qm["config"])
    fresh = diagnose_parity(quality, spread_floor=pm["spread_floor"], refit=False,
        forward_source=pm["forward_source"], discount_source=pm["discount_source"])
    fresh_pairs = fresh.table("pairs").to_dict("records")
    recomputed = _members(fresh_pairs, quotes)
    raw_context = _context(context, quotes, requested)
    pair_rows, pair_ids = [], {}
    for pair in fresh_pairs:
        ids = sorted(pair["source_row_ids"])
        pid = sha256(json.dumps([group_id, ids]).encode()).hexdigest()
        pair_ids.update({sid: pid for sid in ids})
        local = _local_pair(pair, quotes, raw_context, config, requested, source, pm["spread_floor"])
        pair_rows.append(dict(pair_id=pid, source_row_ids=ids, strike=pair["strike"],
            event_time=pair["exchange_time"], n_selected_legs=len(set(ids).intersection(selected_ids)),
            common_status=_state(pair["status"]), common_reason=pair["reason"],
            common_lower=pair["lower"], common_upper=pair["upper"], common_declared_parity=pair["declared_parity"],
            common_distance_outside=pair["distance_outside"], **local,
            common_fail_local_pass=pair["status"] == "fail" and local["local_status"] == "pass"))
    rows = []
    for sid in selected_ids:
        q, pair = quotes[sid], recomputed[sid]
        old = original.get(sid)
        old_status, status = _state(old["status"]) if old else "unavailable", _state(pair["status"])
        scope, event = _scope(q), _stamp(q["exchange_time"])
        opposite = [r for r in records if scope is not None and _scope(r) == scope
                    and r["optiontype"] == {"C": "P", "P": "C"}.get(q["optiontype"])]
        exact = [r for r in opposite if event is not None and _stamp(r["exchange_time"]) == event]
        available = [r for r in opposite if _stamp(r["exchange_time"]) is not None
                     and _stamp(r["exchange_time"]) <= requested]
        if scope is None or q["optiontype"] not in ("C", "P"):
            reason = "missing_or_unsupported_pair_identity"
        elif event is None:
            reason = "selected_event_clock_unavailable"
        elif event > requested:
            reason = "future_selected_event"
        elif _required_time(q["expiry"]) <= requested:
            reason = "expired_selected_quote"
        elif pair["reason"] == "duplicate_pair_legs":
            reason = "ambiguous_exact_pair_legs"
        elif not exact:
            reason = ("opposite_leg_absent" if not opposite else "opposite_leg_clock_unavailable"
                      if not any(_stamp(r["exchange_time"]) is not None for r in opposite) else
                      "opposite_leg_only_future" if not available else "opposite_leg_at_different_event_time")
        else:
            reason = "exact_pair_pass" if status == "pass" else (
                "common_forward_interval_failure" if status == "fail" else pair["reason"] or "unchecked_pair")
        recovery = ("already_supported" if status == old_status == "pass" else
                    "recoverable_original_exact_evidence" if status == "pass" else
                    "original_checked_result_not_reproduced" if old_status in ("pass", "fail") and old_status != status else
                    "observed_common_failure_retained" if status == "fail" else "needs_new_observations")
        gaps = [abs((_required_time(r["exchange_time"])-event).total_seconds()) for r in available] if event is not None else []
        rows.append(dict(source_row_id=sid, contract=q["contract"], strike=q["strike"], optiontype=q["optiontype"],
            expiry=q["expiry"], event_time=q["exchange_time"], pair_id=pair_ids[sid],
            original_status=old_status, recomputed_status=status, attribution=reason, recoverability=recovery,
            original_pair_reason=old["reason"] if old else "original_pair_not_reported",
            opposite_source_ids=[r["source_row_id"] for r in opposite],
            opposite_event_times=[r["exchange_time"] for r in opposite],
            exact_opposite_source_ids=[r["source_row_id"] for r in exact],
            minimum_observed_event_gap_seconds=min(gaps) if gaps else None))
    summary = dict(group_id=group_id, split="calibration" if requested < split else "validation", priority=bool(priority),
        source_rows=len(records), selected_rows=len(rows), original_status=_aggregate(r["original_status"] for r in rows),
        recomputed_status=_aggregate(r["recomputed_status"] for r in rows),
        recoverable_selected_quotes=sum(r["recoverability"] == "recoverable_original_exact_evidence" for r in rows),
        failing_selected_quotes=sum(r["recomputed_status"] == "fail" for r in rows),
        unavailable_selected_quotes=sum(r["recomputed_status"] == "unavailable" for r in rows),
        attributions=sorted({r["attribution"] for r in rows}) if rows else ["empty_selection"])
    return QuoteDiagnosticReport.from_tables(dict(quotes=pd.DataFrame(rows), pairs=pd.DataFrame(pair_rows),
        summary=pd.DataFrame([summary])), dict(kind="parity_attribution", requested_time=requested.isoformat(),
        split_utc=split.isoformat(), group_id=group_id, price_unit=qm["config"]["price_unit"],
        config=qm["config"], recomputed_parity=fresh.to_dict(), receive_availability_verified=False,
        pair_local_scope="separate inverse forward-value/D=1 comparison; no IVs or qualification transfer",
        original_quotes_changed=False, thresholds_fitted=False, refits=0, executable_arbitrage=False))


class Locals(Enum):
    """Offline generated-data parity attribution."""

    SYNTHETIC = 1


def run_local(local: Locals = Locals.SYNTHETIC):
    """Print an attribution report for generated observations with one asynchronous leg."""
    if local != Locals.SYNTHETIC:
        raise ValueError("Unknown example")
    data = generate_simulated_options_data()
    time = data.get_timeindex()[0]
    raw = data.chain_ts[data.chain_ts.exchange_time.eq(time)].copy()
    raw = raw[raw.expiry.eq(raw.expiry.iloc[0])].reset_index(drop=True)
    raw.loc[0, "exchange_time"] -= pd.Timedelta(seconds=1)
    config = QuoteDiagnosticConfig("USD per unit", payoff="standard_european", settlement="cash")
    ids = [f"synthetic:{i}" for i in range(len(raw))]
    quality = diagnose_quotes(raw, config=config, requested_time=time, source_time=time, source_row_ids=ids)
    parity = diagnose_parity(quality, spread_floor=.01)
    result = attribute_parity(quality, parity, ids, group_id="synthetic", split_utc=time+pd.Timedelta(days=1))
    print(result.table("summary").to_string(index=False))
    print(result.table("quotes")[["source_row_id", "attribution", "recoverability"]].to_string(index=False))


if __name__ == "__main__":
    run_local(local=Locals.SYNTHETIC)
