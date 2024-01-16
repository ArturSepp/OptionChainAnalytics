"""
add proprietary data loaders here
the return type is Dict[str, Union[Dict[str, pd.DataFrame], pd.DataFrame]]: where str is SliceColumn

different sources are integrated using wrapper:
ts_data_loader_wrapper()
"""

import pandas as pd
import qis
from typing import Dict, Any, Union, Literal
from enum import Enum

# public data api

from option_chain_analytics import local_path as lp

DERIBIT_LOCAL_PATH = f"{lp.get_resource_path()}\\deribit\\"
TARDIS_FILES_LOCAL_PATH = f"{lp.get_resource_path()}tardis\\"


class DataSource(Enum):
    TARDIS_LOCAL = 1
    DERIBIT_LOCAL = 2


def ts_data_loader_wrapper(data_source: DataSource = DataSource.TARDIS_LOCAL,
                           ticker: str = 'BTC',
                           **kwargs
                           ) -> Dict[str, Any]:
    """
    generic wrapper for loading
    """
    if data_source == DataSource.TARDIS_LOCAL:
        return load_local_tardis_contract_ts_data(ticker=ticker, **kwargs)

    elif data_source == DataSource.DERIBIT_LOCAL:
        return load_local_deribit_contract_ts_data(ticker=ticker, **kwargs)

    else:
        raise NotImplementedError(f"{data_source}")


@qis.timer
def load_local_tardis_contract_ts_data(ticker: str = 'BTC',
                                       local_path: str = TARDIS_FILES_LOCAL_PATH
                                       ) -> Dict[str, Any]:
    """
    this loader is using prop data in feather
    """
    chain_ts = qis.load_df_from_feather(file_name=f"{ticker}_freq_H",
                                        index_col=None,
                                        local_path=local_path)
    spot_data = qis.load_df_from_feather(file_name=f"{ticker}_perp_freq_H",
                                         index_col='timestamp',
                                         local_path=local_path)
    return dict(chain_ts=chain_ts, spot_data=spot_data, ticker=ticker)


@qis.timer
def load_local_deribit_contract_ts_data(ticker: Union[str, Literal['BTC', 'ETH']] = 'BTC',
                                        local_path: str = DERIBIT_LOCAL_PATH
                                        ) -> Dict[str, Any]:
    """
    this loader is using deribit public data in feather
    """
    file_path = f"{local_path}{ticker}_appended_options.feather"  # same as in get_deribit_appended_file_path
    chain_ts = qis.load_df_from_feather(local_path=file_path, index_col=None)
    spot_data = qis.load_df_from_feather(file_name=f"{ticker}_perp_data", local_path=TARDIS_FILES_LOCAL_PATH)
    return dict(chain_ts=chain_ts, spot_data=spot_data, ticker=ticker)


class UnitTests(Enum):
    LOAD_TARDIS_OPTIONS_DF = 1
    LOAD_DERIBIT_OPTIONS_DF = 2


def run_unit_test(unit_test: UnitTests):

    from option_chain_analytics.data.chain_ts import OptionsDataDFs

    pd.set_option('display.max_columns', 500)

    if unit_test == UnitTests.LOAD_TARDIS_OPTIONS_DF:
        options_data_dfs = OptionsDataDFs(**load_local_tardis_contract_ts_data(ticker='ETH'))
        options_data_dfs.print()

    elif unit_test == UnitTests.LOAD_DERIBIT_OPTIONS_DF:
        options_data_dfs = OptionsDataDFs(**load_local_deribit_contract_ts_data(ticker='ETH'))
        options_data_dfs.print()


if __name__ == '__main__':

    unit_test = UnitTests.LOAD_TARDIS_OPTIONS_DF

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
