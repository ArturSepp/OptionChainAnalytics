"""
add p&l analysis of options portfolio
"""
# packages
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import qis as qis
from typing import Dict
from enum import Enum

from option_chain_analytics import compute_option_portfolio_dt, SliceColumn, compute_time_to_maturity


class OptionDatas(Enum):
    option_data1 = {SliceColumn.CONTRACT: 'SPX 21Mar2025 C5875',
                    SliceColumn.EXPIRY: pd.Timestamp('21Mar2025'),
                    SliceColumn.STRIKE: 5875.0,
                    SliceColumn.OPTION_TYPE: 'C',
                    SliceColumn.MARK_IV: 0.1206,
                    SliceColumn.MARK_PRICE: 133.0,
                    SliceColumn.DELTA: 0.35}
    option_data2 = {SliceColumn.CONTRACT: 'SPX 20Dec2024 C5775',
                    SliceColumn.EXPIRY: pd.Timestamp('20Dec2024'),
                    SliceColumn.STRIKE: 5775.0,
                    SliceColumn.OPTION_TYPE: 'C',
                    SliceColumn.MARK_IV: 0.1166,
                    SliceColumn.MARK_PRICE: 100.5,
                    SliceColumn.DELTA: 0.35}
    option_data3 = {SliceColumn.CONTRACT: 'SPX 20Jun2025 C6000',
                    SliceColumn.EXPIRY: pd.Timestamp('20Jun2025'),
                    SliceColumn.STRIKE: 6000.0,
                    SliceColumn.OPTION_TYPE: 'C',
                    SliceColumn.MARK_IV: 0.1238,
                    SliceColumn.MARK_PRICE: 152.5,
                    SliceColumn.DELTA: 0.35}


def run_spx_bump_analysis_17jun2024(option_data: Dict = OptionDatas.option_data2.value):
    """
    apply data from 17jun2024 for compute_option_portfolio_dt
    """
    current_spot = 5433.69
    value_time = pd.Timestamp('17Jun2024')
    event_date = pd.Timestamp('05Nov2024')

    maturity_time = option_data[SliceColumn.EXPIRY]

    ttm = compute_time_to_maturity(maturity_time=maturity_time, value_time=value_time, af=365)
    dt = compute_time_to_maturity(maturity_time=event_date, value_time=value_time, af=365)
    print(f"ttm={ttm}, dt={dt}")

    # create portfolio data
    size = 1.0 / current_spot
    portfolio_report = pd.Series(option_data).to_frame().T
    portfolio_report['sizes'] = size
    print(portfolio_report)

    vol_bumps = np.linspace(-0.02, 0.1, 7)
    deltas = {'log-normal': 0.35, 'normal': 0.25}
    print(vol_bumps)

    delta_pnls = {}
    for key, delta in deltas.items():
        pnls = []
        spot_position = - delta* size  # delta*size
        for vol_bump in vol_bumps:
            total_name = f"vol_bump=+{vol_bump:,.0%}"
            pnl, payoff0 = compute_option_portfolio_dt(portfolio_report=portfolio_report,
                                                       current_spot=current_spot,
                                                       vol_bump=vol_bump,
                                                       change=0.25,
                                                       ttm=ttm,
                                                       dt=dt,
                                                       spot_position=spot_position,
                                                       total_name=total_name)
            spot_grid = pd.Series(pnl.index, index=pnl.index)
            spot_grid_positive = spot_grid[-pnl[total_name] >= 0.0]  # need negative sign for short pnl
            if len(spot_grid_positive.index) > 1:
                lower_be = spot_grid_positive.iloc[0] / current_spot - 1.0
                upper_be = spot_grid_positive.iloc[-1] / current_spot - 1.0
            else:
                lower_be = np.nan
                upper_be = np.nan
            total_name1 = f"{total_name}: breakevens=({lower_be:0.2%}, {upper_be:0.2%})"
            pnl = pnl[total_name].rename(total_name1)
            pnls.append(pnl)
        pnls = pd.concat(pnls, axis=1)
        pnls.index = pnls.index / current_spot - 1.0
        delta_pnls[f"{key}-delta={delta:0.2f}"] = pnls

    with sns.axes_style("darkgrid"):
        fig, axs = plt.subplots(1, 2, figsize=(14, 7), tight_layout=True)
        qis.set_suptitle(fig, title=portfolio_report[SliceColumn.CONTRACT].iloc[0])
        for idx, (key, delta_pnl) in enumerate(delta_pnls.items()):
            qis.plot_line(df=delta_pnl,
                          title=key,
                          xvar_format='{:,.2%}',
                          yvar_format='{:,.2%}',
                          ylabel='Delta hedged P&L %',
                          xlabel='SPX change %',
                          ax=axs[idx])
        qis.align_y_limits_axs(axs)


def run_spx_bump_analysis_for_beta_hedge(option_data: Dict = OptionDatas.option_data1.value,
                                         portfolio_beta: float = 0.5,
                                         hedge_delta: float = 0.35,
                                         hedge_size: float = 1.5,
                                         ax: plt.Subplot = None,
                                         **kwargs
                                         ) -> None:
    """
    apply data from 17jun2024 for compute_option_portfolio_dt
    """
    current_spot = 5433.69
    value_time = pd.Timestamp('17Jun2024')
    event_date = pd.Timestamp('05Nov2024')

    maturity_time = option_data[SliceColumn.EXPIRY]

    ttm = compute_time_to_maturity(maturity_time=maturity_time, value_time=value_time, af=365)
    dt = compute_time_to_maturity(maturity_time=event_date, value_time=value_time, af=365)
    print(f"ttm={ttm}, dt={dt}")

    # create portfolio data
    size = 1.0 / current_spot
    portfolio_report = pd.Series(option_data).to_frame().T
    portfolio_report['sizes'] = size
    print(portfolio_report)

    vol_bumps = np.linspace(-0.02, 0.1, 7)

    pnls = []
    spot_position = (portfolio_beta-hedge_size*hedge_delta) * size  # delta*size
    for vol_bump in vol_bumps:
        total_name = f"Hedged P&L vol=+{vol_bump:,.0%}"
        pnl, payoff0 = compute_option_portfolio_dt(portfolio_report=portfolio_report,
                                                   current_spot=current_spot,
                                                   vol_bump=vol_bump,
                                                   change=0.25,
                                                   ttm=ttm,
                                                   dt=dt,
                                                   spot_position=spot_position,
                                                   total_name=total_name)

        zero_index = np.abs(pnl.index-current_spot).argmin()
        min_return = pnl.index / current_spot - 1.0
        total_name1 = f"{total_name}: p&l(@ 0%)={pnl[total_name].iloc[zero_index]:0.1%}, p&l(@ {min_return[0]:0.0%})={pnl[total_name].iloc[0]:0.1%}"
        pnl = pnl[total_name].rename(total_name1)
        pnls.append(pnl)
    pnls = pd.concat(pnls, axis=1)
    pnls.index = pnls.index / current_spot - 1.0

    unhedged_name = f"Unhedged P&L: p&l(@ 0%)={0.0:0.1%}, p&l(@ {pnls.index[0]:0.0%})={pnls.index[0]*portfolio_beta:0.1%}"
    pnls.insert(loc=0, column=unhedged_name, value=pnls.index*portfolio_beta)

    if ax is None:
        with sns.axes_style("darkgrid"):
            fig, ax = plt.subplots(1, 1, figsize=(14, 7), tight_layout=True)
    qis.plot_line(df=pnls,
                  xvar_format='{:,.1%}',
                  yvar_format='{:,.1%}',
                  ylabel='Delta hedged P&L %',
                  xlabel='SPX change %',
                  ax=ax,
                  **kwargs)


def plot_saa_portfolio_hedges(option_data: Dict = OptionDatas.option_data1.value) -> None:

    portfolio_betas_sizes = {'Income-SAA': (0.31, 0.9),
                             'Conservative-SAA': (0.41, 1.2),
                             'Balanced-SAA': (0.50, 1.5),
                             'Growth-SAA': (0.63, 1.85)}

    with sns.axes_style("darkgrid"):
        fig, axs = plt.subplots(2, 2, figsize=(16, 10), tight_layout=True)
        axs = qis.to_flat_list(axs)
        qis.set_suptitle(fig, title=option_data[SliceColumn.CONTRACT])

        for idx, (key, betas_sizes) in enumerate(portfolio_betas_sizes.items()):
            title = f"{key}: SPX beta={betas_sizes[0]:0.2f}, hedge size={betas_sizes[1]:0.2f}"
            run_spx_bump_analysis_for_beta_hedge(option_data=option_data,
                                                 portfolio_beta=betas_sizes[0],
                                                 hedge_delta=option_data[SliceColumn.DELTA],
                                                 hedge_size=betas_sizes[1],
                                                 title=title,
                                                 ax=axs[idx])
        qis.align_y_limits_axs(axs)


class UnitTests(Enum):
    SPX_BUMP_ANALYSIS_17JUN2024 = 1
    BETA_HEDGE = 2
    BETA_HEDGE_FOR_SAA_PORTFOLIOS = 3


def run_unit_test(unit_test: UnitTests):

    if unit_test == UnitTests.SPX_BUMP_ANALYSIS_17JUN2024:
        # tickers = ['SPY']
        run_spx_bump_analysis_17jun2024(option_data=OptionDatas.option_data1.value)

    elif unit_test == UnitTests.BETA_HEDGE:
        run_spx_bump_analysis_for_beta_hedge(option_data=OptionDatas.option_data1.value)

    elif unit_test == UnitTests.BETA_HEDGE_FOR_SAA_PORTFOLIOS:
        plot_saa_portfolio_hedges(option_data=OptionDatas.option_data1.value)

    plt.show()


if __name__ == '__main__':

    unit_test = UnitTests.BETA_HEDGE_FOR_SAA_PORTFOLIOS

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
