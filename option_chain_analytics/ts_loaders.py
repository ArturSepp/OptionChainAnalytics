"""
add prop data loaders here
the return type is Dict[str, Union[Dict[str, pd.DataFrame], pd.DataFrame]]: where str is SliceColumn
"""
from typing import Dict, Any
from enum import Enum

# public data api
from option_chain_analytics.public_apis.deribit import load_deribit_contract_ts_data

# prop data api
from prop.tardis.deribit_local import load_contract_ts_data_tardis


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
        return load_contract_ts_data_tardis(ticker=ticker, **kwargs)

    elif data_source == DataSource.DERIBIT_LOCAL:
        return load_deribit_contract_ts_data(ticker=ticker, **kwargs)

    else:
        raise NotImplementedError(f"{data_source}")
