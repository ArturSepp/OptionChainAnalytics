"""
analytics for generation of roll maturities for options rolls into front-coming Fridays
"""
# packages
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Union

import pandas as pd
import qis
from qis import TimePeriod

from option_chain_analytics.option_data import OptionsDataDFs
from option_chain_analytics.reconstruction import create_chain_at_time


class RollMaturitySelection(Enum):
    WEEKLY_FRIDAY = 1   # Friday roll to next Friday expiry
    BIWEEKLY_FRIDAY = 2   # By-weekly Friday roll to 2w next Friday expiry
    MONTHLY_LAST_FRIDAY = 3  # Monthly Friday roll to next month Friday expiry
    BUSINESS_DAYS_1W_FRIDAY = 4  # Every business day roll referencing next week Friday expiry
    BUSINESS_DAYS_2W_FRIDAY = 5  # Every business day roll referencing upto next two Friday expiries
    BUSINESS_DAYS_1M_FRIDAY = 6  # Every business day roll referencing upto next one month Friday expiries
    WEEKLY_FRIDAY_1M_FRIDAY = 7  # Every friday roll referencing next weekly Fridays expiries upto next one month Friday
    WEEKLY_EX_1W_FRIDAY_1M_FRIDAY = 8  # Every friday roll referencing next second weekly Fridays expiries upto next one month Friday
    QUARTERLY_LAST_FRIDAY = 9  # every quarter
    CALENDAR_DAY_OVERNIGHT_ROLL = 10  # overnight rolls


def get_next_roll_maturities(value_time: pd.Timestamp,
                             maturity_selection: RollMaturitySelection = RollMaturitySelection.WEEKLY_FRIDAY,
                             hour_offset: int = 8,  # corresponds to the hour of roll implementation
                             min_days_to_next_friday: int = 7,
                             min_days_to_next_quarter: int = 30,
                             max_days_for_monthly_roll: int = 42
                             ) -> Union[List[pd.Timestamp], pd.DatetimeIndex]:
    """
    generate a schedule of fridays for next rolls
    """
    if maturity_selection == RollMaturitySelection.WEEKLY_FRIDAY:
        time_period = TimePeriod(value_time + pd.offsets.Day(min_days_to_next_friday), value_time + pd.offsets.Day(21))
        next_fridays = qis.generate_dates_schedule(time_period=time_period, freq='W-FRI', hour_offset=hour_offset)
        mat_dates = [next_fridays[0]]

    elif maturity_selection == RollMaturitySelection.BIWEEKLY_FRIDAY:
        time_period = TimePeriod(value_time + pd.offsets.Day(2 * min_days_to_next_friday), value_time + pd.offsets.Day(21))
        next_fridays = qis.generate_dates_schedule(time_period=time_period, freq='2W-FRI', hour_offset=hour_offset)
        mat_dates = [next_fridays[0]]

    elif maturity_selection == RollMaturitySelection.MONTHLY_LAST_FRIDAY:
        time_period = TimePeriod(value_time + pd.offsets.Day(min_days_to_next_friday), value_time + pd.offsets.Day(2 * max_days_for_monthly_roll))
        next_fridays = qis.generate_dates_schedule(time_period=time_period, freq='M-FRI', hour_offset=hour_offset)
        mat_dates = [next_fridays[0]]

    elif maturity_selection == RollMaturitySelection.BUSINESS_DAYS_1W_FRIDAY:
        # this week rolls every b day to next friday epiry
        time_period = TimePeriod(value_time + pd.offsets.Day(min_days_to_next_friday), value_time + pd.offsets.Day(14))
        next_fridays = qis.generate_dates_schedule(time_period=time_period, freq='W-FRI', hour_offset=hour_offset)
        mat_dates = [next_fridays[0]]

    elif maturity_selection == RollMaturitySelection.BUSINESS_DAYS_2W_FRIDAY:
        # this week rolls every b day to next friday epiry
        time_period = TimePeriod(value_time + pd.offsets.Day(min_days_to_next_friday), value_time + pd.offsets.Day(21))
        next_fridays = qis.generate_dates_schedule(time_period=time_period, freq='W-FRI', hour_offset=hour_offset)
        mat_dates = next_fridays

    elif maturity_selection == RollMaturitySelection.BUSINESS_DAYS_1M_FRIDAY:
        time_period = TimePeriod(value_time + pd.offsets.Day(min_days_to_next_friday),
                                 value_time + pd.offsets.Day(max_days_for_monthly_roll))
        next_fridays = qis.generate_dates_schedule(time_period=time_period, freq='W-FRI', hour_offset=hour_offset)
        mat_dates = next_fridays

    elif maturity_selection == RollMaturitySelection.WEEKLY_FRIDAY_1M_FRIDAY:
        time_period = TimePeriod(value_time + pd.offsets.Day(min_days_to_next_friday),
                                 value_time + pd.offsets.Day(max_days_for_monthly_roll))
        next_fridays = qis.generate_dates_schedule(time_period=time_period, freq='W-FRI', hour_offset=hour_offset)
        mat_dates = next_fridays

    elif maturity_selection == RollMaturitySelection.WEEKLY_EX_1W_FRIDAY_1M_FRIDAY:
        time_period = TimePeriod(value_time + pd.offsets.Day(2 * min_days_to_next_friday),
                                 value_time + pd.offsets.Day(max_days_for_monthly_roll))
        next_fridays = qis.generate_dates_schedule(time_period=time_period, freq='W-FRI', hour_offset=hour_offset)
        mat_dates = next_fridays

    elif maturity_selection == RollMaturitySelection.QUARTERLY_LAST_FRIDAY:
        # min shift of 30 day to next quarter
        time_period = TimePeriod(value_time + pd.offsets.Day(min_days_to_next_quarter),
                                 value_time + pd.offsets.Day(min_days_to_next_quarter + 181))
        next_fridays = qis.generate_dates_schedule(time_period=time_period, freq='Q-FRI', hour_offset=hour_offset)
        mat_dates = [next_fridays[0]]

    elif maturity_selection == RollMaturitySelection.CALENDAR_DAY_OVERNIGHT_ROLL:
        time_period = TimePeriod(value_time + pd.offsets.Day(1), value_time + pd.offsets.Day(2))
        trading_days = qis.generate_dates_schedule(time_period=time_period, freq='D', hour_offset=hour_offset)
        mat_dates = trading_days

    else:
        raise NotImplementedError

    return mat_dates


def get_roll_maturity_slices_at_value_time(options_data_dfs: OptionsDataDFs,
                                           value_time: pd.Timestamp,
                                           maturity_selection: RollMaturitySelection = RollMaturitySelection.WEEKLY_FRIDAY,
                                           is_apply_open_interest_filter: bool = True,
                                           hour_offset: int = 8  # corresponds to the hour of roll implementation
                                           ) -> List[str]:
    """
    generate a slice ids for next rolls from value_time
    """
    mat_dates = get_next_roll_maturities(value_time=value_time,
                                         maturity_selection=maturity_selection,
                                         hour_offset=hour_offset)
    chain = create_chain_at_time(options_data=options_data_dfs, value_time=value_time)
    if chain is not None:
        slice_ids = chain.get_slice_id_for_mat_dates(mat_dates, is_apply_open_interest_filter=is_apply_open_interest_filter)
    else:
        slice_ids = []

    return slice_ids


def generate_roll_maturities(options_data_dfs: OptionsDataDFs,
                             time_period: TimePeriod,
                             maturity_selection: RollMaturitySelection = RollMaturitySelection.WEEKLY_FRIDAY,
                             is_apply_open_interest_filter: bool = False,
                             hour_offset: int = 8,   # corresponds to the hour of roll implementation
                             max_num_days_for_monthly_roll: int = 42
                             ) -> Dict[pd.Timestamp, List[str]]:
    """
    generate a schedule of fridays for next week up to 1m1w and get available chains maturities
    the output is the dictionary of rebalancing timestamp and the list of maturities to roll model portolio
    does not take into account strike space only open interest
    """
    # set trading days first
    if maturity_selection == RollMaturitySelection.WEEKLY_FRIDAY:
        # add one week to include the next weekly roll
        this = time_period.shift_end_date_by_days(num_days=7, backward=False)
        trading_days = qis.generate_dates_schedule(this, freq='W-FRI', hour_offset=hour_offset)

    elif maturity_selection == RollMaturitySelection.BIWEEKLY_FRIDAY:
        # add one week to include the next weekly roll
        this = time_period.shift_end_date_by_days(num_days=14, backward=False)
        trading_days = qis.generate_dates_schedule(this, freq='2W-FRI', hour_offset=hour_offset)

    elif maturity_selection == RollMaturitySelection.MONTHLY_LAST_FRIDAY:
        this = time_period.shift_end_date_by_days(num_days=2*max_num_days_for_monthly_roll, backward=False)
        trading_days = qis.generate_dates_schedule(this, freq='M-FRI', hour_offset=hour_offset)

    elif maturity_selection == RollMaturitySelection.BUSINESS_DAYS_1W_FRIDAY:
        trading_days = qis.generate_dates_schedule(time_period, freq='B', hour_offset=hour_offset)

    elif maturity_selection == RollMaturitySelection.BUSINESS_DAYS_2W_FRIDAY:
        trading_days = qis.generate_dates_schedule(time_period, freq='B', hour_offset=hour_offset)

    elif maturity_selection == RollMaturitySelection.BUSINESS_DAYS_1M_FRIDAY:
        trading_days = qis.generate_dates_schedule(time_period, freq='B', hour_offset=hour_offset)

    elif maturity_selection == RollMaturitySelection.WEEKLY_FRIDAY_1M_FRIDAY:
        trading_days = qis.generate_dates_schedule(time_period, freq='W-FRI', hour_offset=hour_offset)

    elif maturity_selection == RollMaturitySelection.WEEKLY_EX_1W_FRIDAY_1M_FRIDAY:
        trading_days = qis.generate_dates_schedule(time_period, freq='W-FRI', hour_offset=hour_offset)

    elif maturity_selection == RollMaturitySelection.QUARTERLY_LAST_FRIDAY:
        # add one quarter to include the next weekly roll
        this = time_period.shift_end_date_by_days(num_days=91, backward=False)
        trading_days = qis.generate_dates_schedule(this, freq='Q-FRI', hour_offset=hour_offset)

    elif maturity_selection == RollMaturitySelection.CALENDAR_DAY_OVERNIGHT_ROLL:
        # generate extra days to cover the last week roll
        this = time_period.shift_end_date_by_days(num_days=2, backward=False)
        trading_days = qis.generate_dates_schedule(this, freq='D', hour_offset=hour_offset)

    else:
        raise NotImplementedError(f"maturity_selection = {maturity_selection}")

    roll_maturities = {}
    for date in trading_days:
        slice_ids = get_roll_maturity_slices_at_value_time(options_data_dfs=options_data_dfs,
                                                           value_time=date,
                                                           maturity_selection=maturity_selection,
                                                           is_apply_open_interest_filter=is_apply_open_interest_filter,
                                                           hour_offset=hour_offset)
        if len(slice_ids) > 0:
            roll_maturities[date] = slice_ids

    return roll_maturities
