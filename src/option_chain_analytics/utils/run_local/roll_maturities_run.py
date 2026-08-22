"""Inspect roll dates, available slices, and generated maturity schedules."""

from enum import Enum

import pandas as pd
from qis import TimePeriod

from option_chain_analytics.data.loaders import DataSource, ts_data_loader_wrapper
from option_chain_analytics.option_data import OptionsDataDFs
from option_chain_analytics.utils.roll_maturities import (
    RollMaturitySelection,
    generate_roll_maturities,
    get_next_roll_maturities,
    get_roll_maturity_slices_at_value_time,
)


class Locals(Enum):
    """Available roll-maturity development diagnostics."""

    ROLLS_AT_TIMESTAMP = 1
    ROLL_SLICES_AT_TIMESTAMP = 2
    ROLL_MATURITIES = 3


def run_local(local: Locals) -> None:
    """Run the selected roll-maturity development diagnostic."""
    ticker = 'BTC'
    options_data_dfs = OptionsDataDFs(
        **ts_data_loader_wrapper(ticker=ticker, data_source=DataSource.TARDIS_LOCAL)
    )
    time_period = TimePeriod('2022-01-01 00:00:00+00:00', '2023-04-03 00:00:00+00:00')
    time_period.print()

    if local == Locals.ROLLS_AT_TIMESTAMP:
        value_time = pd.Timestamp.utcnow()
        for maturity_selection in RollMaturitySelection:
            mat_dates = get_next_roll_maturities(
                value_time=value_time,
                maturity_selection=maturity_selection,
                hour_offset=11,
                min_days_to_next_friday=4,
            )
            print(f'{maturity_selection} = {mat_dates}')

    elif local == Locals.ROLL_SLICES_AT_TIMESTAMP:
        value_time = pd.Timestamp('2023-04-26 00:00:00+00:00')
        for maturity_selection in RollMaturitySelection:
            slice_ids = get_roll_maturity_slices_at_value_time(
                options_data_dfs=options_data_dfs,
                value_time=value_time,
                maturity_selection=maturity_selection,
                hour_offset=8,
            )
            print(f'{maturity_selection} = {slice_ids}')

    elif local == Locals.ROLL_MATURITIES:
        maturity_selection = RollMaturitySelection.QUARTERLY_LAST_FRIDAY
        roll_maturities = generate_roll_maturities(
            options_data_dfs=options_data_dfs,
            maturity_selection=maturity_selection,
            time_period=time_period,
        )
        for key, value in roll_maturities.items():
            print(f'{key}: {value}')


if __name__ == '__main__':
    run_local(local=Locals.ROLLS_AT_TIMESTAMP)
