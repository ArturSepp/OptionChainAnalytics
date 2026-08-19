"""Data generators and optional provider integrations.

Provider modules are imported lazily so the deterministic simulation path does
not require credentials or provider-specific dependencies.
"""

from typing import Any

from option_chain_analytics.data.simulated import generate_simulated_options_data

__all__ = [
    'generate_simulated_options_data',
    'build_thetadata_eod_cache',
    'load_thetadata_eod_cache',
    'load_thetadata_eod_options_data',
    'map_thetadata_eod_options_data',
    'update_deribit_options_data',
]


def __getattr__(name: str) -> Any:
    if name in {'build_thetadata_eod_cache', 'load_thetadata_eod_cache'}:
        from option_chain_analytics.data.thetadata_cache import (
            build_thetadata_eod_cache,
            load_thetadata_eod_cache,
        )

        return {
            'build_thetadata_eod_cache': build_thetadata_eod_cache,
            'load_thetadata_eod_cache': load_thetadata_eod_cache,
        }[name]
    if name == 'update_deribit_options_data':
        from option_chain_analytics.data.deribit import update_deribit_options_data

        return update_deribit_options_data
    if name in {'load_thetadata_eod_options_data', 'map_thetadata_eod_options_data'}:
        from option_chain_analytics.data.thetadata import (
            load_thetadata_eod_options_data,
            map_thetadata_eod_options_data,
        )

        return {
            'load_thetadata_eod_options_data': load_thetadata_eod_options_data,
            'map_thetadata_eod_options_data': map_thetadata_eod_options_data,
        }[name]
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
