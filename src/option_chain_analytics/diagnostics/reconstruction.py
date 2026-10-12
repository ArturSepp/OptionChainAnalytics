"""Read-only reconstruction provenance outside canonical quote frames and caches."""

from __future__ import annotations

import numpy as np
import pandas as pd

from option_chain_analytics.diagnostics.quotes import QuoteDiagnosticConfig, diagnose_quotes
from option_chain_analytics.diagnostics.parity import diagnose_parity
from option_chain_analytics.diagnostics.report import QuoteDiagnosticReport, _utc
from option_chain_analytics.option_data import OptionsDataDFs
from option_chain_analytics.option_chain import SlicesChain
from option_chain_analytics.reconstruction import create_chain_at_time


def reconstruct_with_diagnostics(
    options_data: OptionsDataDFs,
    value_time: pd.Timestamp,
    *,
    config: QuoteDiagnosticConfig,
    spread_floor: float,
    time_selection: str = "exact",
    refit_parity: bool = False,
    discount_anchor: float | None = None,
    target_maturities: tuple[str, ...] = (),
) -> tuple[SlicesChain | None, QuoteDiagnosticReport]:
    """Reconstruct through the existing API and report every selected source row.

    Parameters
    ----------
    options_data : OptionsDataDFs
        Normalized history. Whole snapshots are selected, never per-contract fills.
    value_time : pandas.Timestamp
        Aware request time, kept separate from the actual selected feed timestamp.
    config : QuoteDiagnosticConfig
        Quote quality conventions and thresholds; no automatic quality filtering.
    spread_floor : float
        Parity scaling floor in converted per-unit price units.
    time_selection : {'exact', 'previous'}
        Existing point-in-time reconstruction policy, preserved unchanged.
    refit_parity, discount_anchor
        Optional existing robust parity refit and explicit fixed discount.
    target_maturities : tuple of str
        Optional maturity IDs to include in the missing-coverage report.

    Returns
    -------
    tuple of SlicesChain or None and QuoteDiagnosticReport
        Legacy chain plus quality/parity/provenance sidecar. Source IDs are absolute
        row positions in the supplied history, stable for repeated requests against
        that history. They are not identifiers across reordered/revised datasets.
        Canonical quote frames and caches gain no columns.
    """
    requested = _utc(value_time, "value_time")
    chain = create_chain_at_time(options_data, requested, time_selection=time_selection)
    source = chain.value_time if chain is not None else None
    raw = options_data.chain_ts.iloc[:0].copy()
    positions = np.array([], dtype=int)
    if source is not None:
        positions = np.flatnonzero(options_data.chain_ts.exchange_time.eq(source).to_numpy())
        raw = options_data.chain_ts.iloc[positions].copy()
    quality = diagnose_quotes(
        raw,
        config=config,
        requested_time=requested,
        source_time=source,
        source_row_ids=[f"source:{i}" for i in positions],
        target_maturities=target_maturities,
    )
    parity = diagnose_parity(quality, spread_floor=spread_floor, refit=refit_parity, discount_anchor=discount_anchor)
    rows = []
    duplicates = raw.contract.duplicated(keep="first").to_numpy()
    for i, (_, row) in enumerate(raw.iterrows()):
        contract, maturity = row.contract, str(row.mat_id)
        reason, stage = "", "slice_retained"
        if duplicates[i]:
            reason, stage = "duplicate_contract_keep_first", "snapshot_deduplication"
        elif chain is None or maturity not in chain.expiry_slices:
            reason, stage = "missing_maturity_or_unavailable_forward", "expiry_reconstruction"
        else:
            expiry = chain.expiry_slices[maturity]
            retained = pd.concat([expiry.calls, expiry.puts]).contract
            if contract not in set(retained):
                reason = "invalid_optiontype" if row.optiontype not in ("C", "P") else "duplicate_strike_keep_last"
                stage = "slice_deduplication"
        rows.append(
            dict(
                source_row_id=f"source:{positions[i]}",
                contract=contract,
                mat_id=row.mat_id,
                underlying_index=row.underlying_index,
                expiry=row.expiry,
                optiontype=row.optiontype,
                strike=row.strike,
                source_time=source,
                stage=stage,
                exclusion_reason=reason,
                retained=stage == "slice_retained",
            )
        )
    provenance = pd.DataFrame(
        rows,
        columns=[
            "source_row_id",
            "contract",
            "mat_id",
            "underlying_index",
            "expiry",
            "optiontype",
            "strike",
            "source_time",
            "stage",
            "exclusion_reason",
            "retained",
        ],
    )
    n_retained = int(provenance.retained.sum())
    counts = pd.DataFrame(
        [
            dict(
                n_input=len(raw),
                n_contract_unique=len(raw) - int(duplicates.sum()),
                n_slice_retained=n_retained,
                n_excluded=len(raw) - n_retained,
                reconciled=n_retained + int(provenance.exclusion_reason.ne("").sum()) == len(raw),
            )
        ]
    )
    tables = {name: quality.table(name) for name in quality.to_dict()["tables"]}
    tables.update(
        parity=parity.table("pairs"),
        parity_expiries=parity.table("expiries"),
        parity_eligibility=parity.table("eligibility"),
        provenance=provenance,
        counts=counts,
    )
    return chain, QuoteDiagnosticReport.from_tables(
        tables,
        quality.metadata
        | dict(
            kind="reconstruction_diagnostics",
            time_selection=time_selection,
            parity=parity.metadata,
            source_history_rows=len(options_data.chain_ts),
            row_identity="source_history_position",
            reconstruction_policy="existing contract keep-first and per-side strike keep-last",
            selection_status="pass" if chain is not None else "not_checked",
            selection_reason="" if chain is not None else "no_permitted_snapshot",
        ),
    )
