"""
define analytics for portfolio p&l analysis
"""
# packages
import numpy as np
import pandas as pd
from typing import Tuple

import vanilla_option_pricers as bsm
from option_chain_analytics.option_chain import SliceColumn


def compute_portfolio_payoff(portfolio_report: pd.DataFrame,
                             current_spot: float,
                             spot_grid: np.ndarray = None,
                             spot_position_units: float = None,
                             change: float = 0.5,
                             total_name: str = 'Total P&L',
                             is_usd_pnl: bool = True
                             ) -> Tuple[pd.DataFrame, float]:
    """
    compute option portfolio payoff on a grid
    portfolio_report has columns of data SliceColumn + sizes
    """
    if spot_grid is None:
        spot_grid = np.linspace(100.0*np.floor(current_spot*(1.0-change)/100.0), 100.0*np.ceil(current_spot*(1.0+change)/100.0), 200)
    payoff, payoff0 = np.zeros_like(spot_grid), 0.0
    for strike, optiontype, size in zip(portfolio_report[SliceColumn.STRIKE],
                                        portfolio_report[SliceColumn.OPTION_TYPE],
                                        portfolio_report['sizes']):
        if optiontype == 'C':
            payoff += size*np.maximum(spot_grid-strike, 0.0)
            payoff0 += size*np.maximum(current_spot-strike, 0.0)
        elif optiontype == 'P':
            payoff += size*np.maximum(strike-spot_grid, 0.0)
            payoff0 += size*np.maximum(strike-current_spot, 0.0)
        else:
            raise NotImplementedError
    pnl = pd.Series(payoff, index=spot_grid, name='Options Payoff')
    if spot_position_units is not None and np.abs(spot_position_units) > 0.0:
        pnl = pnl.to_frame()
        spot_pnl = (spot_grid-current_spot) * spot_position_units
        pnl['Spot P&L'] = spot_pnl
        pnl[total_name] = payoff + spot_pnl
    else:
        pnl = pnl.rename(total_name).to_frame()

    if not is_usd_pnl:
        # pnl = pnl.divide(qis.np_array_to_df_columns(spot_grid, n_col=len(pnl.columns)))
        pnl = pnl.divide(spot_grid, axis=0)
        payoff0 = payoff0 / current_spot

    return pnl, payoff0


def compute_option_portfolio_dt(portfolio_report: pd.DataFrame,
                                current_spot: float,
                                ttm: float = 0.1,
                                dt: float = 0.00,
                                spot_grid: np.ndarray = None,
                                spot_position: float = None,  # delta*size
                                change: float = 0.5,
                                vol_bump: float = 0.0,
                                total_name: str = 'Total P&L'
                                ) -> Tuple[pd.DataFrame, float]:
    """
    compute option portfolio value change on a spot grid and dt
    portfolio_report has columns of data SliceColumn + sizes
    """
    if spot_grid is None:
        spot_grid = np.linspace(100.0*np.floor(current_spot*(1.0-change)/100.0), 100.0*np.ceil(current_spot*(1.0+change)/100.0), 200)
    payoff, payoff0 = np.zeros_like(spot_grid), 0.0
    for strike, optiontype, size, vol, mark_price in zip(portfolio_report[SliceColumn.STRIKE],
                                                         portfolio_report[SliceColumn.OPTION_TYPE],
                                                         portfolio_report['sizes'],
                                                         portfolio_report[SliceColumn.MARK_IV],
                                                         portfolio_report[SliceColumn.MARK_PRICE]):
        grid_price = bsm.compute_bsm_forward_grid_prices(ttm=ttm - dt,
                                                         forwards=spot_grid,
                                                         strike=strike,
                                                         vol=vol+vol_bump,
                                                         optiontype=optiontype)
        payoff += size*(grid_price-mark_price)
    pnl = pd.Series(payoff, index=spot_grid, name='Options Payoff')
    if spot_position is not None and np.abs(spot_position) > 0.0:
        pnl = pnl.to_frame()
        spot_pnl = (spot_grid-current_spot) * spot_position
        pnl['Spot P&L'] = spot_pnl
        pnl[total_name] = payoff + spot_pnl
    else:
        pnl = pnl.rename(total_name).to_frame()

    return pnl, payoff0
