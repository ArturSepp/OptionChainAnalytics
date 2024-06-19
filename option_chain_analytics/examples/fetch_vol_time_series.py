
import pandas as pd
import qis as qis
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Tuple
from qis import timer, TimePeriod
from enum import Enum

from option_chain_analytics import OptionsDataDFs, generate_atm_vols_skew
from option_chain_analytics.ts_loaders import ts_data_loader_wrapper, DataSource
from option_chain_analytics import local_path as lp


@timer
def fetch_atm_vols_skew(options_data_dfs: OptionsDataDFs,
                        time_period: TimePeriod = None,
                        freq: str = 'D',
                        hour_offset: int = 8,
                        days_before_roll: int = 7
                        ) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    fetch atm vols and aligned prices:
    """
    atm_vols, skews = generate_atm_vols_skew(options_data_dfs=options_data_dfs,
                                             time_period=time_period, freq=freq, hour_offset=hour_offset,
                                             days_before_roll=days_before_roll)
    price_data = options_data_dfs.get_spot_price(index=atm_vols.index)
    return atm_vols, skews, price_data


def analyse_skew():
    tickers = ['BTC', 'ETH']
    with sns.axes_style("darkgrid"):
        fig, axs = plt.subplots(1, 2, figsize=(14, 7), tight_layout=True)

        for idx, ticker in enumerate(tickers):
            df = qis.load_df_from_csv(file_name=f"{ticker}_atm_vols_skew", local_path=lp.get_resource_path())
            df = df.asfreq('B').dropna(axis=0, how='any')
            returns = df[ticker].pct_change()
            x = returns.multiply(df['skew'].shift()).rename('skew*return')
            y = df['atm_vol'].diff().rename('vol change')
            xy = pd.concat([x, y], axis=1)
            qis.plot_scatter(df=xy, title=f"{ticker} skew-beta", ax=axs[idx])


class UnitTests(Enum):
    FETCH_ATM_VOLS = 1
    ANALYSE_SKEW = 2


def run_unit_test(unit_test: UnitTests):

    ticker = 'BTC'

    if unit_test == UnitTests.FETCH_ATM_VOLS:
        time_period = TimePeriod('2023-01-01 00:00:00+00:00', '2023-01-30 00:00:00+00:00', tz='UTC')
        options_data_dfs = OptionsDataDFs(**ts_data_loader_wrapper(ticker=ticker, data_source=DataSource.TARDIS_LOCAL))
        atm_vols, skews, price_data = fetch_atm_vols_skew(options_data_dfs=options_data_dfs,
                                                          days_before_roll=7,
                                                          time_period=None)
        df = pd.concat([price_data.rename(ticker), atm_vols.rename('atm_vol'), skews], axis=1)
        print(df)
        qis.save_df_to_csv(df=df, file_name=f"{ticker}_atm_vols_skew", local_path=lp.get_resource_path())

    elif unit_test == UnitTests.ANALYSE_SKEW:
        analyse_skew()

    plt.show()


if __name__ == '__main__':

    unit_test = UnitTests.ANALYSE_SKEW

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
