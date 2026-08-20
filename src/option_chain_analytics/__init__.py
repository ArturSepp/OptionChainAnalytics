
"""Point-in-time option-chain containers and reconstruction analytics."""

from option_chain_analytics.conventions import (
    NearestStrikeOnGrid,
    StrikeSelection,
    compute_time_to_maturity,
    mat_to_timestamp,
)
from option_chain_analytics.data.loaders import DataSource, ts_data_loader_wrapper
from option_chain_analytics.data.simulated import generate_simulated_options_data
from option_chain_analytics.data.thetadata import (
    load_thetadata_eod_options_data,
    load_thetadata_eod_options_timeseries,
    map_thetadata_eod_options_data,
)
from option_chain_analytics.data.thetadata_cache import (
    build_thetadata_eod_cache,
    load_thetadata_eod_cache,
)
from option_chain_analytics.option_chain import (
    ExpirySlice,
    SliceColumn,
    SlicesChain,
    get_contract_execution_price,
)
from option_chain_analytics.option_data import FuturesChainTs, OptionsDataDFs
from option_chain_analytics.reconstruction import create_chain_at_time, create_chain_timeseries
from option_chain_analytics.utils.portfolio_payoff import (
    compute_option_portfolio_dt,
    compute_portfolio_payoff,
)
from option_chain_analytics.visuals.chain_report import run_chain_report
from option_chain_analytics.visuals.slices import plot_slice_open_interest, plot_slice_vols

__all__ = [
    'DataSource',
    'ExpirySlice',
    'FuturesChainTs',
    'NearestStrikeOnGrid',
    'OptionsDataDFs',
    'SliceColumn',
    'SlicesChain',
    'StrikeSelection',
    'compute_option_portfolio_dt',
    'compute_portfolio_payoff',
    'compute_time_to_maturity',
    'build_thetadata_eod_cache',
    'create_chain_at_time',
    'create_chain_timeseries',
    'generate_simulated_options_data',
    'get_contract_execution_price',
    'load_thetadata_eod_options_data',
    'load_thetadata_eod_cache',
    'load_thetadata_eod_options_timeseries',
    'map_thetadata_eod_options_data',
    'mat_to_timestamp',
    'plot_slice_open_interest',
    'plot_slice_vols',
    'run_chain_report',
    'ts_data_loader_wrapper',
]
