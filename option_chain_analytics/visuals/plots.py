"""
axiliary anlytics for plots
"""
import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
import qis as qis
from matplotlib.lines import Line2D
import matplotlib.ticker as mticker
from typing import Tuple, Optional, List, Dict, Union


def create_dummy_line(**kwargs):
    return Line2D([], [], **kwargs)


def plot_vol_slice_fit_error_bar(bid_vols: Dict[str, pd.Series],  # should include 'bid', 'ask', model
                  ask_vols: Dict[str, pd.Series],
                  model_vols: Dict[str, pd.Series],
                  title: str = None,
                  strike_name: str = 'strike',
                  bid_name: str = 'bid',
                  ask_name: str = 'ask',
                  model_color: str = 'black',
                  atm_points: Dict[str, Tuple[float, float]] = None,
                  yvar_format: str = '{:.0%}',
                  xvar_format: Optional[str] = '{:0,.0f}',
                  fontsize: int = 12,
                  ylabel: str = 'Implied vols',
                  x_rotation: int = 0,
                  ax: plt.Subplot = None,
                  **kwargs
                  ) -> Optional[plt.Figure]:

    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=(8, 8))
    else:
        fig = None

    # merge vols
    clean_model_vols = {}
    lower_errors = {}
    upper_errors = {}
    for bid_key, ask_key, model_key in zip(bid_vols.keys(), ask_vols.keys(), model_vols.keys()):
        df = pd.concat([bid_vols[bid_key].rename(bid_name),
                        ask_vols[ask_key].rename(ask_name),
                        model_vols[model_key].rename(model_key)],
                       axis=1).sort_index().dropna()
        clean_model_vols[model_key] = df[model_key]
        lower_errors[model_key] = df[bid_name]
        upper_errors[model_key] = df[ask_name]
    clean_model_vols_df = pd.DataFrame.from_dict(clean_model_vols, orient='columns')

    # add fitted vols line
    if len(model_vols.keys()) == 1:
        palette = [model_color]
    else:
        palette = sns.husl_palette(len(model_vols.keys()), h=.5)
    sns.lineplot(data=clean_model_vols_df, palette=palette, dashes=False, ax=ax)
    #for legend, color in zip(clean_model_vols_df.columns, palette):
    #    lines.append((legend, {'color': color}))

    lines = []  # for legend
    # add mids with error bars
    for idx, (bid_key, ask_key, model_key) in enumerate(zip(bid_vols.keys(), ask_vols.keys(), model_vols.keys())):
        x = clean_model_vols[model_key].index.to_numpy()
        mark = clean_model_vols[model_key].to_numpy()
        lower_error = lower_errors[model_key].to_numpy()
        upper_error = upper_errors[model_key].to_numpy()
        ax.scatter(x, y=lower_error, marker="^", color=palette[idx], s=3, linewidth=1)
        ax.scatter(x, y=upper_error, marker="v", color=palette[idx], s=3, linewidth=1)
        ax.scatter(x, y=mark, marker="o", color=palette[idx], s=3, linewidth=1)
        mid = 0.5*(lower_error+upper_error)
        error = sns.utils.ci_to_errsize((lower_error, upper_error), mid)
        error = np.where(error>0.0, error, 0.0)
        ax.errorbar(x=x, y=mid, yerr=error, fmt='none', color=palette[idx], linewidth=1)
        lines.append((model_key, {'color': palette[idx], 'linestyle': '-', 'marker': 'o'}))
        lines.append((f"{bid_key} bid/ask", {'color': palette[idx], 'linestyle': '', 'marker': "^"}))

    # atm points
    if atm_points is not None:
        for key, (x, y) in atm_points.items():
            ax.scatter(x, y, marker='*', color='navy', s=40, linewidth=5)
            lines.append(('ATM', {'color': 'navy', 'linestyle': '', 'marker': '*'}))

    ax.legend([create_dummy_line(**l[1]) for l in lines],  # Line handles
              [l[0] for l in lines],  # Line titles
              loc='upper center',
              framealpha=0,
              fontsize=fontsize,
              ncol=2)
    qis.set_legend_colors(ax)

    if x_rotation != 0:
        [tick.set_rotation(x_rotation) for tick in ax.get_xticklabels()]

    # ticks
    if xvar_format is not None:
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda z, _: xvar_format.format(z)))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda z, _: yvar_format.format(z)))

    ax.set_ylabel(ylabel, fontsize=fontsize)
    ax.set_xlabel(strike_name, fontsize=fontsize)
    if title is not None:
        ax.set_title(title, fontsize=fontsize, color='darkblue')

    return fig


def plot_price_slice_fit(bid_price: pd.Series,
                         ask_price: pd.Series,
                         model_prices: Union[pd.Series, pd.DataFrame],
                         title: str = None,
                         strike_name: str = 'strike',
                         bid_name: str = 'bid',
                         ask_name: str = 'ask',
                         mid_name: str = 'mid',
                         model_color: str = 'black',
                         bid_color: str = 'red',
                         ask_color: str = 'green',
                         mid_color: str = 'lightslategrey',
                         is_add_mids: bool = False,
                         atm_points: Dict[str, Tuple[float, float]] = None,
                         yvar_format: str = '{:,.2f}',
                         xvar_format: Optional[str] = '{:0,.0f}',
                         fontsize: int = 12,
                         ylabel: str = 'Prices',
                         x_rotation: int = 0,
                         is_log: bool = False,
                         ax: plt.Subplot = None,
                         **kwargs
                         ) -> Optional[plt.Figure]:
    """
    plot model fit in price space
    """
    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=(8, 8))
    else:
        fig = None

    if isinstance(model_prices, pd.Series):  # optimise for frame
        model_prices = model_prices.to_frame()

    # for legend
    lines = []

    # add fitted vols line
    if len(model_prices.columns) == 1:
        palette = [model_color]
    else:
        palette = sns.husl_palette(len(model_prices.columns), h=.5)
    sns.lineplot(data=model_prices, palette=palette, dashes=False, ax=ax)
    for legend, color in zip(model_prices.columns, palette):
        lines.append((legend, {'color': color}))

    # add mids with error bars
    if is_add_mids:
        aligned_vols = pd.concat([bid_price, ask_price], axis=1)
        mid = np.mean(aligned_vols.to_numpy(), axis=1)
        lower_error = aligned_vols.iloc[:, 0].to_numpy()
        upper_error = aligned_vols.iloc[:, 1].to_numpy()
        error = sns.utils.ci_to_errsize((lower_error, upper_error), mid)
        ax.errorbar(x=aligned_vols.index.to_numpy(), y=mid, yerr=error, fmt='o', color=mid_color)
        lines.append((mid_name, {'color': mid_color, 'linestyle': '', 'marker': 'o'}))

    # add bid ask scatter
    legends_data = {bid_name: bid_color, ask_name: ask_color}
    for vol, legend in zip([bid_price, ask_price], legends_data.keys()):
        vol.index.name = strike_name
        vol.name = legend
        data = vol.to_frame().reset_index()
        sns.scatterplot(x=strike_name, y=legend, data=data, color=legends_data[legend],
                        edgecolor=None,
                        facecolor=None,
                        s=40,
                        linewidth=3,
                        marker='_',
                        ax=ax)
        lines.append((legend, {'color': legends_data[legend], 'linestyle': '', 'marker': '_'}))

    # atm points
    if atm_points is not None:
        for key, (x, y) in atm_points.items():
            ax.scatter(x, y, marker='*', color='navy', s=40, linewidth=5)
            lines.append(('ATM', {'color': 'navy', 'linestyle': '', 'marker': '*'}))

    ax.legend([create_dummy_line(**l[1]) for l in lines],  # Line handles
              [l[0] for l in lines],  # Line titles
              loc='upper center',
              framealpha=0,
              ncol=2)
    qis.set_legend_colors(ax)

    if x_rotation != 0:
        [tick.set_rotation(x_rotation) for tick in ax.get_xticklabels()]

    # ticks
    if xvar_format is not None:
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda z, _: xvar_format.format(z)))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda z, _: yvar_format.format(z)))

    ax.set_ylabel(ylabel, fontsize=fontsize)
    if title is not None:
        ax.set_title(title, fontsize=fontsize, color='darkblue')

    if is_log:
        ax.set_yscale('log')

    return fig


def plot_vols(vols: pd.DataFrame,
              ax: plt.Subplot = None,
              linestyles: List[str] = None,
              markers: List[str] = None,
              label_x_y: Dict[str, Tuple[float, float]] = None,
              **kwargs
              ) -> None:

    kwargs = qis.update_kwargs(kwargs,
                               dict(ncol=3, legend_loc='upper center',
                                    xvar_format='{:,.2f}',
                                    yvar_format='{:.0%}',
                                    markersize=10))
    if ax is None:
        with sns.axes_style("darkgrid"):
            fig, ax = plt.subplots(1, 1, figsize=(6, 6), tight_layout=True)

    markers = markers or ["o"]*len(vols.columns)
    linestyles = linestyles or ['-']*len(vols.columns)
    qis.plot_line(df=vols,
                  linestyles=linestyles,
                  markers=markers,
                  ylabel='Implied Vol',
                  ax=ax,
                  **kwargs)

    if label_x_y is not None:
        qis.add_scatter_points(ax=ax, label_x_y=label_x_y, linewidth=10)


def map_deltas_to_str(bsm_deltas: np.ndarray, delta_str_format: str = '0.2f') -> List[str]:
    """
    map deltas to str of 0.2f
    deltas below 0.05 are mapped as 0.04
    """
    slice_index = []
    index_str = np.empty_like(bsm_deltas, dtype=str)
    for idx, x in enumerate(bsm_deltas):
        if np.abs(x) < 0.05:
            x_str = f"{x:0.4f}"
        else:
            x_str = f"{x:{delta_str_format}}"
        # check for non overlaps
        if idx > 0:
            if x_str == index_str[idx - 1]:
                if x < 0.0:  # decrease previous delta
                    slice_index[idx-1] = f"{bsm_deltas[idx-1]:0.4f}"
                else:
                    x_str = f"{x:0.4f}"
        slice_index.append(x_str)
    return slice_index
