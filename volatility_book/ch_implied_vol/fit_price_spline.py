"""
illustrations of using spline fitter
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import qis as qis
from typing import List
from enum import Enum
from option_chain_analytics.option_chain import SliceColumn
from option_chain_analytics.visuals.plots import plot_slice_price_fit

# option_chain_anaytics
from option_chain_analytics import WeightType, infer_mark_price_with_spline

# set path to recourses
from option_chain_analytics import local_path as lp
LOCAL_PATH = lp.get_local_resource_path()
OUTPUT_PATH = lp.get_output_path()


def compute_call_put_price_spline(slice_df: pd.DataFrame,
                                  weight_type: WeightType = WeightType.TIME_VALUE,
                                  eps: float = 0.0001,
                                  call_slice_name: str = 'Arb-free call spline',
                                  put_slice_name: str = 'Arb-free put spline'
                                  ) -> pd.DataFrame:

    spot_price = np.nanmean(slice_df[SliceColumn.SPOT_PRICE.value])
    calls_slice = slice_df.loc[slice_df[SliceColumn.OPTION_TYPE.value] == 'C', :]
    puts_slice = slice_df.loc[slice_df[SliceColumn.OPTION_TYPE.value] == 'P', :]

    call_marks = infer_mark_price_with_spline(option_slice=calls_slice,
                                              spot_price=spot_price,
                                              eps=eps,
                                              is_calls=True,
                                              weight_type=weight_type,
                                              ).rename(call_slice_name)

    put_marks = infer_mark_price_with_spline(option_slice=puts_slice,
                                             spot_price=spot_price,
                                             eps=eps,
                                             is_calls=False,
                                             weight_type=weight_type,
                                             ).rename(put_slice_name)

    mark_prices = pd.concat([call_marks, put_marks], axis=1)
    return mark_prices


def report_chain_fits(chain_df: pd.DataFrame) -> List[plt.Figure]:
    dfs = chain_df.groupby('mat_id', sort=False)
    figs = []
    for mat_id, slice_df in dfs:
        print(mat_id)
        with sns.axes_style("darkgrid"):
            fig, ax = plt.subplots(1, 1, figsize=(14, 12), tight_layout=True)
            figs.append(fig)
            qis.set_suptitle(fig, f"maturity={mat_id}")
            mark_prices = compute_call_put_price_spline(slice_df=slice_df)
            slice_df = slice_df.set_index('strike', drop=False).sort_index()
            plot_slice_price_fit(bid_price=slice_df[SliceColumn.BID_PRICE.value],
                                 ask_price=slice_df[SliceColumn.ASK_PRICE.value],
                                 model_prices=mark_prices,
                                 ax=ax)
    return figs


def compute_interpolated_price_grid():
    pass


class UnitTests(Enum):
    RUN_SPLINE = 1
    REPORT_CHAIN_FITS = 2


def run_unit_test(unit_test: UnitTests):
    file_name = 'SPY_20240614152847'
    chain_df = qis.load_df_from_csv(file_name='SPY_20240614152847',
                                    parse_dates=False,
                                    local_path=LOCAL_PATH)

    if unit_test == UnitTests.RUN_SPLINE:
        dfs = chain_df.groupby('mat_id', sort=False)
        for mat_id, data in dfs:
            print(mat_id)
        # slice_df = dfs.get_group('14-Jun-24').set_index('strike', drop=False).sort_index()
        slice_df = dfs.get_group('17-Jun-24').set_index('strike', drop=False).sort_index()
        # slice_df = dfs.get_group('16-Aug-24').set_index('strike', drop=False).sort_index() # for figure
        # slice_df = dfs.get_group('30-Aug-24').set_index('strike', drop=False).sort_index()
        # slice_df = dfs.get_group('20-Sep-24').set_index('strike', drop=False).sort_index()

        mark_prices = compute_call_put_price_spline(slice_df=slice_df)
        plot_slice_price_fit(bid_price=slice_df[SliceColumn.BID_PRICE.value],
                             ask_price=slice_df[SliceColumn.ASK_PRICE.value],
                             model_prices=mark_prices)
        plt.show()

    elif unit_test == UnitTests.REPORT_CHAIN_FITS:
        figs = report_chain_fits(chain_df=chain_df)
        qis.save_figs_to_pdf(figs=figs, file_name=file_name, local_path=OUTPUT_PATH)


if __name__ == '__main__':

    unit_test = UnitTests.REPORT_CHAIN_FITS

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
