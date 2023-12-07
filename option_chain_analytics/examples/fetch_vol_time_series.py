
import pandas as pd
from typing import Tuple
from qis import timer, TimePeriod
from enum import Enum

from option_chain_analytics import OptionsDataDFs, generate_atm_vols
from option_chain_analytics.ts_loaders import ts_data_loader_wrapper, DataSource


@timer
def fetch_atm_vols(options_data_dfs: OptionsDataDFs,
                   time_period: TimePeriod = None,
                   freq: str = 'D',
                   hour_offset: int = 8,
                   days_before_roll: int = 7
                   ) -> Tuple[pd.Series, pd.Series]:
    """
    fetch atm vols and aligned prices:
    """
    atm_vols = generate_atm_vols(options_data_dfs=options_data_dfs,
                                 time_period=time_period, freq=freq, hour_offset=hour_offset,
                                 days_before_roll=days_before_roll)
    price_data = options_data_dfs.get_spot_price(index=atm_vols.index)
    return atm_vols, price_data


class UnitTests(Enum):
    FETCH_ATM_VOLS = 1


def run_unit_test(unit_test: UnitTests):

    ticker = 'ETH'

    if unit_test == UnitTests.FETCH_ATM_VOLS:
        time_period = TimePeriod('2023-01-01 00:00:00+00:00', '2023-01-30 00:00:00+00:00', tz='UTC')
        options_data_dfs = OptionsDataDFs(**ts_data_loader_wrapper(ticker=ticker, data_source=DataSource.TARDIS_LOCAL))
        atm_vols, price_data = fetch_atm_vols(options_data_dfs=options_data_dfs,
                                              days_before_roll=7,
                                              time_period=None)
        df = pd.concat([price_data.rename(ticker), atm_vols.rename('atm_vol')], axis=1)
        print(df)
        # qis.save_df_to_csv(df=df, file_name=f"{ticker}_atm_vols", local_path=local_path.get_resource_path())


if __name__ == '__main__':

    unit_test = UnitTests.FETCH_ATM_VOLS

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
