from typing import Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import qis
import seaborn as sns

from option_chain_analytics.option_chain import ExpirySlice, SliceColumn
from option_chain_analytics.visuals.plots import map_deltas_to_str


def plot_slice_open_interest(eslice: ExpirySlice,
                             title: str = None,
                             ax: plt.Subplot = None,
                             **kwargs
                             ) -> None:
    df = eslice.get_slice_open_interest()
    kwargs = qis.update_kwargs(kwargs,
                               dict(x_rotation=90, ncol=2, legend_loc='upper center', first_color_fixed=True))
    qis.plot_bars(df=df,
                  stacked=True,
                  var_format='{:,.0f}',
                  yvar_format='{:,.0f}',
                  is_top_totals=False,
                  # add_bar_values=True,
                  title=title,
                  ax=ax,
                  **kwargs)


def plot_slice_vols(eslice: ExpirySlice,
                    is_delta_space: bool = False,
                    delta_bounds: Tuple[Optional[float], Optional[float]] = None,
                    is_filtered: bool = False,
                    title: str = None,
                    delta_str_format: str = '0.2f',
                    ax: plt.Subplot = None,
                    **kwargs
                    ) -> None:

    df, strikes = eslice.get_bid_mark_ask_vols(is_delta_space=is_delta_space, delta_bounds=delta_bounds, is_filtered=is_filtered)
    if is_delta_space:
        max_delta = np.max(df.index.to_numpy())  # ATM is max absolute delta
        label_x_y = {'ATM strike': (f"{max_delta:{delta_str_format}}", df.loc[max_delta, SliceColumn.MARK_IV])}
        df.index = map_deltas_to_str(df.index.to_numpy(), delta_str_format=delta_str_format)
        xlabel, xvar_format, x_rotation = 'Delta', None, 90
    else:
        atm_strike = eslice.get_atm_option_strike()
        label_x_y = {'ATM strike': (atm_strike, df.loc[atm_strike, SliceColumn.MARK_IV])}
        xlabel, xvar_format,  x_rotation = 'Strike', '{:,.0f}', 0

    kwargs = qis.update_kwargs(kwargs,
                               dict(ncol=3, legend_loc='upper center',
                                    xvar_format=xvar_format,
                                    yvar_format='{:,.2%}',
                                    markersize=10,
                                    x_rotation=x_rotation))
    if ax is None:
        with sns.axes_style("darkgrid"):
            fig, ax = plt.subplots(1, 1, figsize=(6, 6), tight_layout=True)

    qis.plot_line(df=df,
                  linestyles=['', '-', ''],
                  markers=["^", "o", "v"],
                  ylabel='Implied Vol',
                  xlabel=xlabel,
                  title=title,
                  ax=ax,
                  **kwargs)
    for label, (x_value, y_value) in label_x_y.items():
        ax.scatter([x_value], [y_value], s=80, color='navy', zorder=5)
        ax.annotate(
            label,
            xy=(x_value, y_value),
            xytext=(5, 5),
            textcoords='offset points',
            color='navy',
        )


def plot_slice_vols_with_oi(eslice: ExpirySlice,
                            delta_bounds: Tuple[Optional[float], Optional[float]] = None,
                            is_filtered: bool = False,
                            is_delta_space: bool = False,
                            title: str = None,
                            delta_str_format: str = '0.2f',
                            ax: plt.Subplot = None,
                            **kwargs
                            ) -> None:
    if ax is None:
        with sns.axes_style("darkgrid"):
            fig, ax = plt.subplots(1, 1, figsize=(6, 9), tight_layout=True)

    plot_slice_vols(eslice=eslice,
                    is_delta_space=is_delta_space,
                    delta_bounds=delta_bounds,
                    is_filtered=is_filtered,
                    delta_str_format=delta_str_format,
                    title=title,
                    ax=ax,
                    **kwargs)

    ymin, ymax = ax.get_ylim()
    if ymin < 0.0:
        ax.set_ylim([-0.01, None]) # slices with zero bids

    # add oi bars
    ax = ax.twinx()
    df = eslice.get_slice_open_interest()
    # need to reindex to account for delta_bounds=delta_bounds, is_filtered=is_filtered
    df1, strikes = eslice.get_bid_mark_ask_vols(is_delta_space=is_delta_space, delta_bounds=delta_bounds,
                                                is_filtered=is_filtered)
    df = df.reindex(index=strikes.to_numpy())
    if is_delta_space:
        df.index = map_deltas_to_str(df.index.to_numpy(), delta_str_format=delta_str_format)  # should match vols
        x_vals = np.arange(len(df.index))
        widths = 0.25
    else:
        x_vals = df.index.to_numpy()
        widths = (
            np.minimum(np.min(np.abs(x_vals[1:] - x_vals[:-1])), 100.0)
            if len(x_vals) > 1
            else max(0.01 * abs(float(x_vals[0])), 1.0)
        )
    oi_sets = {'Puts OI': 'steelblue', 'Calls OI': 'turquoise'}
    for idx, (key, color) in enumerate(oi_sets.items()):
        ax.bar(x_vals, df.iloc[:, idx].to_numpy(), widths, color=color, alpha=0.5, label=key, edgecolor='none', linewidth=0)
    ax.legend(bbox_to_anchor=(0.4, 0.95), loc='upper center', ncol=2)
    ax.set_ylabel('Contracts OI')
    ax.set_ylim([0.0, None])
