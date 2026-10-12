"""Optional plots of stored quote-quality and parity evidence."""

import matplotlib.pyplot as plt
import pandas as pd

from option_chain_analytics.diagnostics.report import QuoteDiagnosticReport


def plot_quote_diagnostics(report: QuoteDiagnosticReport):
    """Plot quote quality annotations and a parity residual panel.

    Parameters
    ----------
    report : QuoteDiagnosticReport
        Quote-quality or reconstruction report. Parity is plotted only when present.

    Returns
    -------
    matplotlib.figure.Figure
        Independent figure; no legacy chain-report defaults are modified.
        Crosses denote diagnostic failures, not automatic quote exclusion.
    """
    quotes = report.table("quotes")
    figure, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for maturity, group in quotes.groupby("mat_id"):
        mid = 0.5 * (pd.to_numeric(group.bid_iv) + pd.to_numeric(group.ask_iv))
        axes[0].scatter(group.strike, 100 * mid, label=str(maturity), s=22)
        failed = group.n_failed_checks.gt(0)
        axes[0].scatter(group.loc[failed, "strike"], 100 * mid.loc[failed], marker="x", color="black", s=40)
    if not quotes.empty:
        axes[0].legend(fontsize="small")
    axes[0].set(xlabel="Strike", ylabel="Mid IV, percent", title="Quote quality (cross = flagged row)")
    if "parity" in report.to_dict()["tables"]:
        parity = report.table("parity")
        for maturity, group in parity.groupby("mat_id"):
            axes[1].scatter(group.strike, group.scaled_residual, label=str(maturity), s=22)
        axes[1].axhline(0, color="black", linewidth=0.7)
        values = pd.to_numeric(parity.scaled_residual).dropna()
        if not values.empty:
            axes[1].set_ylim(min(-1.1, float(values.min()) * 1.1), max(1.1, float(values.max()) * 1.1))
        unchecked = parity.status.isin(["not_checked", "not_applicable"]).sum()
        axes[1].text(0.02, 0.03, f"Unchecked pair groups: {unchecked}", transform=axes[1].transAxes, fontsize="small")
    else:
        axes[1].text(0.5, 0.5, "Parity not checked", ha="center", transform=axes[1].transAxes)
    axes[1].set(
        xlabel="Strike", ylabel="Parity residual / combined half-spread floor", title="Declared forward/discount"
    )
    return figure
