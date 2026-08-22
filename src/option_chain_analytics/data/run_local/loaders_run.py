"""Load and print local Tardis or Deribit option histories."""

from enum import Enum

import pandas as pd


class Locals(Enum):
    """Available provider-loader development diagnostics."""

    LOAD_TARDIS_OPTIONS_DF = 1
    LOAD_DERIBIT_OPTIONS_DF = 2


def run_local(local: Locals) -> None:
    """Run the selected local Tardis or Deribit loader diagnostic."""
    from option_chain_analytics.data.deribit import load_local_deribit_contract_ts_data
    from option_chain_analytics.data.tardis import load_local_tardis_contract_ts_data
    from option_chain_analytics.option_data import OptionsDataDFs

    pd.set_option('display.max_columns', 500)

    if local == Locals.LOAD_TARDIS_OPTIONS_DF:
        options_data_dfs = OptionsDataDFs(**load_local_tardis_contract_ts_data(ticker='ETH'))
        options_data_dfs.print()

    elif local == Locals.LOAD_DERIBIT_OPTIONS_DF:
        options_data_dfs = OptionsDataDFs(**load_local_deribit_contract_ts_data(ticker='ETH'))
        options_data_dfs.print()


if __name__ == '__main__':
    run_local(local=Locals.LOAD_TARDIS_OPTIONS_DF)
