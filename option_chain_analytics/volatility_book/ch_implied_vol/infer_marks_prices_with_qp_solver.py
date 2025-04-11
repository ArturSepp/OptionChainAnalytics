"""
illustrations of using spline fitter
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import qis as qis
from typing import List
from enum import Enum

from option_chain_analytics.fitters.utils import plot_slice_fits, plot_price_spline_fits
from option_chain_analytics.option_chain import SliceColumn
import vanilla_option_pricers as bsm

# option_chain_anaytics
from option_chain_analytics.fitters.qp_price_fitter import (WeightType,
                                                            estimate_b_spline,
                                                            bspline_interpolation,
                                                            fit_slice_mark_prices_implied_vols_with_qp_solver)


def report_chain_fits_with_qp_solver(chain_df: pd.DataFrame,
                                     weight_type: WeightType = WeightType.TIME_VALUE,
                                     eps: float = 0.0001,
                                     bid_ask_contraint_band: float = 0.1,  # deflate / inflate
                                     verbose: bool = False
                                     ) -> List[plt.Figure]:
    dfs = chain_df.groupby('mat_id', sort=False)
    figs = []
    for mat_id, slice_df in dfs:
        print(mat_id)
        slice_df = slice_df.set_index('strike', drop=False).sort_index()
        slice_fit_outputs = fit_slice_mark_prices_implied_vols_with_qp_solver(slice_df=slice_df,
                                                                              weight_type=weight_type,
                                                                              eps=eps,
                                                                              bid_ask_contraint_band=bid_ask_contraint_band,
                                                                              verbose=verbose)
        fig = plot_slice_fits(slice_df=slice_df, slice_fit_outputs=slice_fit_outputs, expiry=mat_id, bounds=(0.01, 0.95))
        qis.set_suptitle(fig, title=f"{mat_id}")
        figs.append(fig)

    return figs


def compute_interpolated_price_grid(slice_df: pd.DataFrame,
                                    weight_type: WeightType = WeightType.BID_ASK_SPREAD,
                                    eps: float = 0.00001,
                                    bid_ask_contraint_band: float = 0.0,  # deflate / inflate
                                    degree: int = 3,
                                    verbose: bool = True
                                    ) -> pd.DataFrame:

    slice_fit_outputs, call_spline, put_spline = fit_slice_mark_prices_implied_vols_with_qp_solver(slice_df=slice_df,
                                                                                                   weight_type=weight_type,
                                                                                                   eps=eps,
                                                                                                   bid_ask_contraint_band=bid_ask_contraint_band,
                                                                                                   verbose=verbose,
                                                                                                   is_apply_bspline=True)
    fig = plot_slice_fits(slice_df=slice_df, slice_fit_outputs=slice_fit_outputs, expiry='mat_id', bounds=(0.01, 0.95))

    call_marks = slice_fit_outputs.call_mark_prices.sort_index()

    x = call_marks.index.to_numpy()
    y = call_marks.to_numpy()
    strike_grid = np.linspace(call_marks.index[0], call_marks.index[-1], 10001)
    b_spline = call_spline  # estimate_b_spline(x=x, y=y, eps=eps, degree=degree)
    spline_prices = bspline_interpolation(x=strike_grid, b_spline=b_spline)
    #spline_prices = bsm.compute_bsm_vanilla_price_vector(ttm=0.25, forward=5380.52, strike=strike_grid, vol=0.25,  optiontype='C', discfactor=1.0)
    spline_prices = pd.Series(spline_prices, index=strike_grid, name='spline')
    plot_price_spline_fits(mark_prices=call_marks, spline_prices=spline_prices)


def compute_interpolated_price_grid_spline(slice_df: pd.DataFrame,
                                    weight_type: WeightType = WeightType.BID_ASK_SPREAD,
                                    eps: float = 0.00001,
                                    bid_ask_contraint_band: float = 0.0,  # deflate / inflate
                                    degree: int = 3,
                                    verbose: bool = True
                                    ) -> pd.DataFrame:

    slice_fit_outputs, call_spline, put_spline = fit_slice_mark_prices_implied_vols_with_qp_solver(slice_df=slice_df,
                                                                          weight_type=weight_type,
                                                                          eps=0.00001,
                                                                          bid_ask_contraint_band=bid_ask_contraint_band,
                                                                          verbose=verbose)
    fig = plot_slice_fits(slice_df=slice_df, slice_fit_outputs=slice_fit_outputs, expiry='mat_id', bounds=(0.01, 0.95))

    call_marks = slice_fit_outputs.call_mark_prices.sort_index()

    x = call_marks.index.to_numpy()
    y = call_marks.to_numpy()
    strike_grid = np.linspace(call_marks.index[0], call_marks.index[-1], 10000)
    b_spline = estimate_b_spline(x=x, y=y, eps=eps, degree=degree)
    spline_prices = bspline_interpolation(x=strike_grid, b_spline=b_spline)
    #spline_prices = bsm.compute_bsm_vanilla_price_vector(ttm=0.25, forward=5380.52, strike=strike_grid, vol=0.25,  optiontype='C', discfactor=1.0)
    spline_prices = pd.Series(spline_prices, index=strike_grid, name='spline')
    plot_price_spline_fits(mark_prices=call_marks, spline_prices=spline_prices)



class UnitTests(Enum):
    RUN_SLICE_FIT_FOR_BOOK_FIGURE = 1
    REPORT_CHAIN_FITS = 2
    INTERPOLATED_PRICE_GRID = 3
    INTERPOLATED_PRICE_GRID_SPLINE = 4


def run_unit_test(unit_test: UnitTests):

    # set path to recourses
    from option_chain_analytics import local_path as lp
    # LOCAL_PATH = "C://Users//uarts//Python//qdev-quant-regime_switch-dev//resources//"
    LOCAL_PATH = lp.get_local_resource_path()
    OUTPUT_PATH = lp.get_output_path()
    LOCAL_FIGURE_PATH = "C://Users//artur//OneDrive//My Papers//Volatility Book//VolatilityBookGithub//chapters//ImpliedVolatility//figures//"

    file_name = 'SPX_20240524160000'

    chain_df = qis.load_df_from_csv(file_name=file_name, parse_dates=False, local_path=LOCAL_PATH)

    if unit_test == UnitTests.RUN_SLICE_FIT_FOR_BOOK_FIGURE:
        expiry = '20Sep2024'
        dfs = chain_df.groupby('mat_id', sort=False)
        for mat_id, data in dfs:
            print(mat_id)
        slice_df = dfs.get_group(expiry).set_index('strike', drop=False).sort_index()
        slice_fit_outputs, call_spline, put_spline = fit_slice_mark_prices_implied_vols_with_qp_solver(slice_df=slice_df,
                                                                                                       weight_type=WeightType.BID_ASK_SPREAD,
                                                                                                       eps=0.00001,
                                                                                                       bid_ask_contraint_band=0.0,
                                                                                                       verbose=True)
        # plot_slice_fits(slice_df=slice_df, slice_fit_outputs=slice_fit_outputs, bounds=None)
        fig = plot_slice_fits(slice_df=slice_df, slice_fit_outputs=slice_fit_outputs,
                              expiry=expiry,
                              bounds=(0.01, 0.95))

    elif unit_test == UnitTests.REPORT_CHAIN_FITS:
        figs = report_chain_fits_with_qp_solver(chain_df=chain_df,
                                                weight_type=WeightType.BID_ASK_SPREAD,
                                                eps=0.00001,
                                                bid_ask_contraint_band=0.0,
                                                verbose=False
                                                )
        qis.save_figs_to_pdf(figs=figs, file_name=file_name, local_path=OUTPUT_PATH)
        plt.close('all')

    elif unit_test == UnitTests.INTERPOLATED_PRICE_GRID_SPLINE:
        dfs = chain_df.groupby('mat_id', sort=False)
        slice_df = dfs.get_group('20Sep2024').set_index('strike', drop=False).sort_index()
        compute_interpolated_price_grid(slice_df=slice_df,
                                        weight_type=WeightType.BID_ASK_SPREAD,
                                        eps=0.00001,
                                        degree=3,
                                        bid_ask_contraint_band=0.0
                                        )

    plt.show()


if __name__ == '__main__':

    unit_test = UnitTests.INTERPOLATED_PRICE_GRID_SPLINE

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
