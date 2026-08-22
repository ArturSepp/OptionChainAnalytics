"""Run local Deribit path, update, and history-loading diagnostics."""

from enum import Enum

import pandas as pd

from option_chain_analytics.data.deribit import (
    get_deribit_appended_file_path,
    update_deribit_options_data,
)


class Locals(Enum):
    """Available Deribit development diagnostics."""

    FILE_PATH = 1
    UPDATE_OPTIONS_DATA = 2
    LOAD_DERIBIT_OPTIONS_DF = 3


def run_local(local: Locals) -> None:
    """Run the selected local Deribit fetch or loading diagnostic."""
    pd.set_option('display.max_columns', 500)

    if local == Locals.FILE_PATH:
        file_path = get_deribit_appended_file_path(ticker='BTC')
        print(file_path)

    elif local == Locals.UPDATE_OPTIONS_DATA:
        timestamps = update_deribit_options_data()
        print(timestamps)

    elif local == Locals.LOAD_DERIBIT_OPTIONS_DF:
        from option_chain_analytics.data.deribit import load_local_deribit_contract_ts_data
        from option_chain_analytics.option_data import OptionsDataDFs
        from option_chain_analytics.reconstruction import create_chain_at_time

        options_data_dfs = OptionsDataDFs(**load_local_deribit_contract_ts_data(ticker='ETH'))
        options_data_dfs.print()
        print(options_data_dfs.chain_ts.columns)
        time_index = options_data_dfs.get_timeindex()
        print(f'time_index={time_index}')

        value_time = pd.Timestamp('2023-10-27 06:20:03.160939+00:00')
        chain = create_chain_at_time(options_data=options_data_dfs, value_time=value_time)
        chain.print_slices_id()


if __name__ == '__main__':
    run_local(local=Locals.LOAD_DERIBIT_OPTIONS_DF)
