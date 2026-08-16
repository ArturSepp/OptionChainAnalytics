"""Data generators and optional provider integrations.

Provider modules are imported lazily so the deterministic simulation path does
not require credentials or provider-specific dependencies.
"""

from typing import Any

from option_chain_analytics.data.simulated import generate_simulated_options_data

__all__ = [
    'fetch_yahoo_options_live_data',
    'generate_simulated_options_data',
    'update_deribit_options_data',
]


def __getattr__(name: str) -> Any:
    if name == 'update_deribit_options_data':
        from option_chain_analytics.data.deribit import update_deribit_options_data

        return update_deribit_options_data
    if name == 'fetch_yahoo_options_live_data':
        from option_chain_analytics.data.yahoo import fetch_yahoo_options_live_data

        return fetch_yahoo_options_live_data
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
