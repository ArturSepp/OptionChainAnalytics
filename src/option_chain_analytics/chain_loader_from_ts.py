"""
create chain data object with options using time series options data in OptionsDataDFs
"""
# package
from enum import Enum
from typing import Dict, List, Literal, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import qis
from qis import TimePeriod, timer
from qis.utils.np_ops import np_nonan_weighted_avg

from option_chain_analytics.chain_ts import OptionsDataDFs

# analytics
from option_chain_analytics.option_chain import ExpirySlice, SliceColumn, SlicesChain, UnderlyingColumn


# @timer
def create_chain_from_from_options_dfs(options_data_dfs: OptionsDataDFs,
                                       value_time: pd.Timestamp,
                                       time_selection: Literal['exact', 'previous'] = 'exact',
                                       ) -> Optional[SlicesChain]:
    """
    Create a chain at an exact or explicitly previous observation time.
    """
    options_df = options_data_dfs.get_time_slice(
        timestamp=value_time,
        time_selection=time_selection,
    )

    if not options_df.empty:
        selected_value_time = pd.Timestamp(options_df[SliceColumn.EXCHANGE_TIME.value].iloc[0])
        # options_df[SliceColumn.CONTRACT.value] = options_df.index.to_list()
        mat_slice = options_df.groupby(SliceColumn.MATURITY_ID.value)
        expiry_slices, undelying_datas = {}, {}
        for mat, df in mat_slice:
            if np.any(df[SliceColumn.OPEN_INTEREST].isna() == False):
                # forward is contract weighted avs
                forward = np_nonan_weighted_avg(a=df[SliceColumn.FORWARD_PRICE.value],
                                                weights=df[SliceColumn.OPEN_INTEREST])
            else:
                # forward is contract weighted avs
                forward = np.nanmean(df[SliceColumn.FORWARD_PRICE.value])
            if not np.isnan(forward):
                undelying_data = {UnderlyingColumn.EXPIRY_ID: str(mat),
                                  UnderlyingColumn.VALUE_TIME: selected_value_time,
                                  UnderlyingColumn.EXPIRY: df[SliceColumn.EXPIRY].iloc[0],
                                  UnderlyingColumn.SPOT_PRICE: forward,  # to do
                                  UnderlyingColumn.UNDERLYING_INDEX: str(mat),  # to do
                                  UnderlyingColumn.FORWARD_PRICE: forward,  # to do
                                  UnderlyingColumn.IR_RATE: 0.0,
                                  UnderlyingColumn.TTM: df[SliceColumn.TTM].iloc[0]}
                undelying_data = pd.Series(undelying_data)
                expiry_slices[str(mat)] = ExpirySlice(options_df=df, undelying_data=undelying_data)
                undelying_datas[str(mat)] = undelying_data
        undelying_df = pd.DataFrame.from_dict(undelying_datas, orient='index')
        chain = SlicesChain(options_df=options_df,#.set_index(SliceColumn.CONTRACT),
                            undelying_df=undelying_df,
                            expiry_slices=expiry_slices,
                            value_time=selected_value_time)
    else:
        chain = None
    return chain


@timer
def create_chain_timeseries(options_data_dfs: OptionsDataDFs,
                            dates_schedule: pd.DatetimeIndex = None,
                            time_period: TimePeriod = None,
                            freq: str = 'W-FRI',
                            hour_offset: int = 8,
                            time_selection: Literal['exact', 'previous'] = 'previous',
                            ) -> Dict[pd.Timestamp, SlicesChain]:
    """
    create dictionary of timestamp and corresponding slices
    """
    if dates_schedule is None:
        if time_period is None:
            raise ValueError(f"time_period={time_period} must be non Nons")
        dates_schedule = qis.generate_dates_schedule(time_period=time_period,
                                                     freq=freq,
                                                     hour_offset=hour_offset)

    chain_data = {}
    for timestamp in dates_schedule:
        chain = create_chain_from_from_options_dfs(
            options_data_dfs=options_data_dfs,
            value_time=timestamp,
            time_selection=time_selection,
        )
        if chain is not None:
            chain_data[timestamp] = chain
    return chain_data


@timer
def generate_atm_vols_skew(options_data_dfs: OptionsDataDFs,
                           time_period: TimePeriod = None,
                           freq: str = 'D',
                           hour_offset: int = 8,
                           days_before_roll: int = 7
                           ) -> Tuple[pd.Series, pd.Series]:

    """
    fetch time series of atm vols and skew from  options_data_dfs
    """
    if time_period is None:
        time_period = options_data_dfs.get_start_end_date()

    chain_data = create_chain_timeseries(options_data_dfs=options_data_dfs,
                                         time_period=time_period,
                                         freq=freq,
                                         hour_offset=hour_offset)
    vols = {}
    skews = {}
    for date, chain in chain_data.items():
        next_date = date + pd.DateOffset(days=days_before_roll)
        slice_id = chain.get_next_slice_after_date(mat_date=next_date)
        vols[date] = chain.get_atm_vol(slice_id=slice_id)
        skews[date] = chain.get_skew(slice_id=slice_id)
    vols = pd.Series(vols, name='atm_vol')
    skews = pd.Series(skews, name='skew')
    return vols, skews


@timer
def generate_vol_delta_ts(options_data_dfs: OptionsDataDFs,
                          days_map: Dict[str, int] = None,
                          deltas: List[float] = (-0.10, -0.25, 0.50, 0.25, 0.10),
                          freq: str = 'D',
                          hour_offset: Optional[int] = 8,
                          time_period: TimePeriod = None
                          ) -> Tuple[pd.DataFrame, ...]:
    """
    return dataframes of vols with columns = deltas and index = dates
    """
    if time_period is None:
        time_period = options_data_dfs.get_start_end_date()

    chain_data = create_chain_timeseries(options_data_dfs=options_data_dfs,
                                         time_period=time_period,
                                         freq=freq,
                                         hour_offset=hour_offset)
    if days_map is None:
        days_map = {'1d': 1, '2d': 2, '1w': 7, '2w': 10, '1m': 28, '2m': 56, '3m': 84, '2Q': 168}

    is_add_tenor_to_delta_name = False if len(days_map.keys()) == 1 else True
    vols, strikes, options, underlying_prices = {}, {}, {}, {}
    for date, chain in chain_data.items():
        delta_vol_matrix = chain.generate_delta_vol_matrix(value_time=date, days_map=days_map, deltas=deltas)
        if delta_vol_matrix is not None:
            vols_, strikes_, options_, index_prices_ = delta_vol_matrix.get_melted_matrix(is_add_tenor_to_delta_name=is_add_tenor_to_delta_name)
            vols[date] = vols_['vols'].rename(date)
            strikes[date] = strikes_['strikes'].rename(date)
            options[date] = options_['options'].rename(date)
            underlying_prices[date] = index_prices_['underlying_prices_matrix'].rename(date)
    vols = pd.DataFrame.from_dict(vols, orient='index')
    strikes = pd.DataFrame.from_dict(strikes, orient='index')
    options = pd.DataFrame.from_dict(options, orient='index')
    underlying_prices = pd.DataFrame.from_dict(underlying_prices, orient='index')
    return vols, strikes, options, underlying_prices


class UnitTests(Enum):
    CREATE_CHAIN_AT_TS = 1
    CREATE_TS_CHAIN_DATA = 2
    CREATE_WEEKLY_ROLLS = 3
    GENERATE_VOL_DELTA_TS = 4


def run_unit_test(unit_test: UnitTests):

    from option_chain_analytics.ts_loaders import DataSource, ts_data_loader_wrapper

    ticker = 'ETH'
    options_data_dfs = OptionsDataDFs(**ts_data_loader_wrapper(ticker=ticker, data_source=DataSource.TARDIS_LOCAL))

    if unit_test == UnitTests.CREATE_CHAIN_AT_TS:
        date = pd.Timestamp('2022-09-19 08:00:00+00:00')
        chain = create_chain_from_from_options_dfs(options_data_dfs=options_data_dfs, value_time=date)
        chain.save_joint_slices(file_name=f"{ticker}_{date.strftime('%Y%m%d_%H_%M_%S')}")

        next_date = date+pd.DateOffset(days=30)
        slice_id = chain.get_next_slice_after_date(mat_date=next_date)
        print(f"{date}: {slice_id}")
        print(f"{chain.get_atm_put_id(slice_id=slice_id)}, {chain.get_atm_call_id(slice_id=slice_id)}")
        print(f"{chain.get_put_delta_option_id(slice_id=slice_id, delta=-0.25)}")
        print(f"{chain.get_call_delta_option_id(slice_id=slice_id, delta=0.25)}")

        # days_map = {'1d': 1, '2d': 2, '1w': 7, '2w': 14, '1m': 30, '2m': 60, '3m': 90, '2Q': 120,  '3Q': 180}
        # days_map = {'1d': 1, '2d': 2, '1w': 7, '2w': 14, '1m': 30, '2m': 60, '3m': 90, '2Q': 120}
        days_map = {'2d': 2, '1w': 7, '2w': 14, '1m': 30, '2m': 60, '3m': 90}
        delta_vol_matrix = chain.generate_delta_vol_matrix(value_time=date, days_map=days_map)
        delta_vol_matrix.print()

        vols, strikes, options, index_prices = delta_vol_matrix.get_melted_matrix()
        print(vols)
        print(strikes)
        delta_vol_matrix.plot_vol_in_strike()

    elif unit_test == UnitTests.CREATE_TS_CHAIN_DATA:
        chain_data = create_chain_timeseries(options_data_dfs=options_data_dfs,
                                             time_period=options_data_dfs.get_start_end_date(),
                                             freq='W-FRI',
                                             hour_offset=8)
        for key, chain in chain_data.items():
            print(f"{key}, {chain.expiry_slices.keys()}")

    elif unit_test == UnitTests.CREATE_WEEKLY_ROLLS:
        weekly_fridays_rolls = qis.generate_dates_schedule(TimePeriod(pd.Timestamp('2022-05-06 00:00:00+00:00'),
                                                                      qis.get_current_time_with_tz(tz='UTC', days_offset=7)),
                                                           freq='W-FRI',
                                                           hour_offset=8)
        weekly_fridays_rolls = weekly_fridays_rolls[:-2]
        print(weekly_fridays_rolls)

        chain_data = create_chain_timeseries(options_data_dfs=options_data_dfs,
                                             dates_schedule=weekly_fridays_rolls[:-1])

        for date, next_date in zip(weekly_fridays_rolls[:-1], weekly_fridays_rolls[1:]):
            print(f"{date}: {chain_data[date].get_next_slice_after_date(mat_date=next_date)}, "
                  f"{chain_data[date].get_atm_put_id(mat_date=next_date)}")

    elif unit_test == UnitTests.GENERATE_VOL_DELTA_TS:
        time_period = TimePeriod('2023-01-01 00:00:00+00:00', '2023-07-14 00:00:00+00:00', tz='UTC')
        vols, strikes, options, index_prices = generate_vol_delta_ts(options_data_dfs=options_data_dfs,
                                                                     days_map={'1w': 7, '1m': 30},
                                                                     deltas=[-0.10, -0.25, 0.50, 0.25, 0.10],
                                                                     freq='B',
                                                                     hour_offset=8,
                                                                     time_period=time_period)
        print(vols)

    plt.show()


if __name__ == '__main__':

    unit_test = UnitTests.GENERATE_VOL_DELTA_TS

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
