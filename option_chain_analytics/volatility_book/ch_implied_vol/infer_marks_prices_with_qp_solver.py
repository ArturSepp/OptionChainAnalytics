"""
illustrations of using spline fitter

# storing image path
fname = r'g4g.png'

# opening image using pil
image = Image.open(fname).convert("L")

# mapping image to gray scale
plt.imshow(image, cmap='gray')
plt.show()

https://gist.github.com/davidwessman/d2d142fc593fde489d46

"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import qis as qis
from typing import List
from enum import Enum

from option_chain_analytics.fitters.utils import plot_slice_fits
from option_chain_analytics.option_chain import SliceColumn

# option_chain_anaytics
from option_chain_analytics.fitters.qp_price_fitter import (WeightType,
                                                            compute_b_spline,
                                                            bspline_interpolation,
                                                            fit_slice_mark_prices_implied_vols_with_qp_solver)

# set path to recourses
from option_chain_analytics import local_path as lp
# LOCAL_PATH = "C://Users//uarts//Python//qdev-quant-regime_switch-dev//resources//"
LOCAL_PATH = lp.get_local_resource_path()
OUTPUT_PATH = lp.get_output_path()


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
                                  weight_type: WeightType = WeightType.TIME_VALUE,
                                  eps: float = 0.00001,
                                  call_slice_name: str = 'Arb-free call spline',
                                  put_slice_name: str = 'Arb-free put spline',
                                  verbose: bool = True
                                  ) -> pd.DataFrame:

    spot_price = np.nanmean(slice_df[SliceColumn.SPOT_PRICE.value])
    calls_slice = slice_df.loc[slice_df[SliceColumn.OPTION_TYPE.value] == 'C', :]
    puts_slice = slice_df.loc[slice_df[SliceColumn.OPTION_TYPE.value] == 'P', :]

    call_marks = infer_mark_price_with_qp_solver(bid_prices=calls_slice[SliceColumn.BID_PRICE.value],
                                                 ask_prices=calls_slice[SliceColumn.ASK_PRICE.value],
                                                 forward=spot_price,
                                                 eps=eps,
                                                 is_calls=True,
                                                 weight_type=weight_type,
                                                 verbose=verbose
                                                 ).rename(call_slice_name)
    print(call_marks)

    x = call_marks.index.to_numpy()
    y = call_marks.to_numpy()
    x1 = np.linspace(call_marks.index[0], call_marks.index[-1], 300)
    t_knots, spline_coeffs = compute_b_spline(x=x, y=y, is_monotonic=False)
    y_spline1 = bspline_interpolation(x=x1, t_knots=t_knots, spline_coeffs=spline_coeffs)
    spline = pd.Series(y_spline1, index=x1, name='y_spline')
    df = pd.concat([call_marks, spline], axis=1).sort_index()
    qis.plot_line(df=df)


class UnitTests(Enum):
    RUN_SLICE_FIT = 1
    REPORT_CHAIN_FITS = 2
    INTERPOLATED_PRICE_GRID = 3


def run_unit_test(unit_test: UnitTests):

    is_yahoo = False
    if is_yahoo:
        file_name = 'SPY_20240620190830'
    else:
        file_name = 'SPX_20240524160000'

    chain_df = qis.load_df_from_csv(file_name=file_name, parse_dates=False, local_path=LOCAL_PATH)
    # chain_df = qis.load_df_from_excel(file_name=file_name, local_path=LOCAL_PATH)

    if unit_test == UnitTests.RUN_SLICE_FIT:
        dfs = chain_df.groupby('mat_id', sort=False)
        for mat_id, data in dfs:
            print(mat_id)
        slice_df = dfs.get_group('20Sep2024').set_index('strike', drop=False).sort_index()
        slice_fit_outputs = fit_slice_mark_prices_implied_vols_with_qp_solver(slice_df=slice_df,
                                                                              weight_type=WeightType.BID_ASK_SPREAD,
                                                                              eps=0.00001,
                                                                              bid_ask_contraint_band=0.0,
                                                                              verbose=True)
        # plot_slice_fits(slice_df=slice_df, slice_fit_outputs=slice_fit_outputs, bounds=None)
        plot_slice_fits(slice_df=slice_df, slice_fit_outputs=slice_fit_outputs, bounds=(0.01, 0.95))

        plt.show()

    elif unit_test == UnitTests.REPORT_CHAIN_FITS:
        figs = report_chain_fits_with_qp_solver(chain_df=chain_df,
                                                weight_type=WeightType.BID_ASK_SPREAD,
                                                eps=0.00001,
                                                bid_ask_contraint_band=0.0,
                                                verbose=False
                                                )
        qis.save_figs_to_pdf(figs=figs, file_name=file_name, local_path=OUTPUT_PATH)

    elif unit_test == UnitTests.INTERPOLATED_PRICE_GRID:
        dfs = chain_df.groupby('mat_id', sort=False)
        slice_df = dfs.get_group('20Sep2024').set_index('strike', drop=False).sort_index()
        compute_interpolated_price_grid(slice_df=slice_df)

        plt.show()


if __name__ == '__main__':

    unit_test = UnitTests.REPORT_CHAIN_FITS

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
