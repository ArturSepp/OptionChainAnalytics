"""Multi-panel volatility and open-interest reports for option chains.

``run_chain_report`` creates one strike-space and delta-space figure per
expiry. The source-checkout diagnostic in
``option_chain_analytics.visuals.run_local.chain_report_run`` persists the
resulting figure collection through OCA's centralized output path.
"""

from typing import Dict

import matplotlib.pyplot as plt
import seaborn as sns

import option_chain_analytics.visuals.slices as vis

# analytics
from option_chain_analytics.option_chain import SlicesChain

FIG_SIZE = (8.3, 11.7)  # A4 for portrait


def run_chain_report(chain: SlicesChain) -> Dict[str, plt.Figure]:
    """Create strike- and delta-space diagnostic figures for every live expiry.

    Parameters
    ----------
    chain : SlicesChain
        Point-in-time option chain to visualize.

    Returns
    -------
    dict[str, matplotlib.figure.Figure]
        Figures keyed by expiry and filtering configuration.
    """
    figs = {}
    configs = {'Unrestricted': dict(delta_bounds=None, is_filtered=False),
               'Deltas > 0.1': dict(delta_bounds=(-0.1, 0.1), is_filtered=True)}
    for expiry, eslice in chain.expiry_slices.items():
        if eslice.get_ttm() > 0.0:
            for key, vals in configs.items():
                fig = plt.figure(figsize=FIG_SIZE, constrained_layout=True)
                fig.suptitle(f"slice id={eslice.expiry_id}, future price={eslice.forward:,.2f} - {key}",
                             fontweight="bold", fontsize=10, color='blue')
                gs = fig.add_gridspec(nrows=2, ncols=1, wspace=0.0, hspace=0.0)
                with sns.axes_style("darkgrid"):
                    ax = fig.add_subplot(gs[0, 0])
                    vis.plot_slice_vols_with_oi(eslice=eslice, title=f"{eslice.expiry_id} Vols In Strike Space",
                                                is_delta_space=False,
                                                ax=ax, **vals)
                    ax = fig.add_subplot(gs[1, 0])
                    vis.plot_slice_vols_with_oi(eslice=eslice, title=f"{eslice.expiry_id} Vols in Delta Space",
                                                is_delta_space=True,
                                                ax=ax, **vals)
                figs[f"{expiry}_{key}"] = fig
                plt.close(fig)

    return figs
