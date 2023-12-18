"""
old_analytics for fitting vol for log sv model
"""
import numpy as np
import pandas as pd
import qis
import seaborn as sns
import matplotlib.pyplot as plt
from typing import Tuple, Optional, List
from enum import Enum

import option_chain_analytics.fitters.vol_beta_fitter as fvb
from option_chain_analytics.option_chain import SliceColumn, SlicesChain


def run_chain_vol_fit(chain: SlicesChain,
                      delta_bounds: Tuple[Optional[float], Optional[float]] = (-0.05, 0.05)
                      ) -> pd.DataFrame:
    fit_params = {}
    for slice_id, slice_data in chain.expiry_slices.items():
        vols, strikes = slice_data.get_bid_mark_ask_vols(delta_bounds=delta_bounds, is_filtered=False)
        print(f"slice_id={slice_id}, forward={slice_data.forward}")
        print(vols)

        if vols is not None:
            mid_vols = vols[SliceColumn.MARK_IV].to_numpy()
            log_strikes = np.log(strikes.to_numpy() / slice_data.forward)

            fit_params[slice_id] = fvb.fit_logsv_ivols(log_strikes=log_strikes,
                                                       mid_vols=mid_vols,
                                                       ttm=slice_data.get_ttm(),
                                                       is_vega_weights=True)
    fit_params = pd.DataFrame.from_dict(fit_params, orient='index')
    return fit_params


def run_chain_report(chain: SlicesChain,
                     delta_bounds: Tuple[Optional[float], Optional[float]] = (-0.25, 0.25)
                     ) -> List[plt.Figure]:

    fit_params = {}
    figs = []
    for slice_id, slice_data in chain.expiry_slices.items():
        vols, strikes = slice_data.get_bid_mark_ask_vols(delta_bounds=delta_bounds, is_filtered=False)
        print(vols)
        if vols is not None:
            vols = vols.dropna(how='any', axis=0)
            strikes = vols.index
            print(f"slice_id={slice_id}")
            print(vols)

            mid_vols = vols[SliceColumn.MARK_IV].to_numpy()
            log_strikes = np.log(strikes.to_numpy() / slice_data.forward)

            fit_params[slice_id] = fvb.fit_logsv_ivols(log_strikes=log_strikes,
                                                       mid_vols=mid_vols,
                                                       ttm=slice_data.get_ttm(),
                                                       is_vega_weights=True)
            model_vols = fvb.calc_logsv_ivols(log_strikes=log_strikes, **fit_params[slice_id])

            df = pd.concat([vols, pd.Series(model_vols, index=vols.index, name='Fit')], axis=1)

            with sns.axes_style("darkgrid"):
                fig, ax = plt.subplots(1, 1, figsize=(10, 7))
                qis.plot_line(df=df,
                              title=f"{slice_id}",
                              yvar_format='{:,.4%}',
                              ax=ax)
            figs.append(fig)

    fit_params = pd.DataFrame.from_dict(fit_params, orient='index')
    print(fit_params)

    return figs


class UnitTests(Enum):
    DERIBIT_FIT = 1
    YAHOO_FIT = 2


def run_unit_test(unit_test: UnitTests):

    # to get options data
    from option_chain_analytics.data.chain_loader_from_ts import create_chain_from_from_options_dfs
    from option_chain_analytics.data.chain_ts import OptionsDataDFs
    from option_chain_analytics import local_path as local_path

    if unit_test == UnitTests.DERIBIT_FIT:
        from option_chain_analytics.ts_loaders import ts_data_loader_wrapper
        options_data_dfs = OptionsDataDFs(**ts_data_loader_wrapper(ticker='ETH'))
        time_index = options_data_dfs.get_timeindex()
        print(f"time_index={time_index}")
        value_time = pd.Timestamp('2023-11-03 17:30:34.270745+00:00')
        chain = create_chain_from_from_options_dfs(options_data_dfs=options_data_dfs, value_time=value_time)
        fit_params = run_chain_vol_fit(chain=chain)
        print(fit_params)

    elif unit_test == UnitTests.YAHOO_FIT:
        from option_chain_analytics.data.apis.yahoo import load_contract_ts_data

        ticker = 'USO'
        value_time = pd.Timestamp('2023-11-24 17:21:17.248659+00:00')

        ticker = 'SPY'
        value_time = pd.Timestamp('2023-11-26 20:00:00+00:00')

        options_data_dfs = OptionsDataDFs(**load_contract_ts_data(ticker=ticker))
        time_index = options_data_dfs.get_timeindex()
        print(f"time_index={time_index}")
        chain = create_chain_from_from_options_dfs(options_data_dfs=options_data_dfs, value_time=value_time)
        figs = run_chain_report(chain=chain)
        qis.save_figs_to_pdf(figs, file_name=f"{ticker}_vol_fit", local_path=local_path.get_output_path())

        # run_chain_report(chain=chain)

    plt.show()


if __name__ == '__main__':

    unit_test = UnitTests.YAHOO_FIT

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)

