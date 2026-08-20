"""Regression tests for the OCA 5.0 module and reconstruction API cleanup."""

from importlib import import_module

import pytest


def test_reconstruction_api_uses_clear_public_names() -> None:
    """OCA exposes only the clearly named point-in-time reconstruction functions."""
    package = import_module('option_chain_analytics')

    assert callable(package.create_chain_at_time)
    assert callable(package.create_chain_timeseries)
    assert not hasattr(package, 'create_chain_from_from_options_dfs')
    assert not hasattr(package, 'generate_atm_vols_skew')
    assert not hasattr(package, 'generate_vol_delta_ts')


def test_provider_loaders_use_split_data_modules() -> None:
    """Provider adapters and dispatch live in focused data modules."""
    cboe = import_module('option_chain_analytics.data.cboe')
    deribit = import_module('option_chain_analytics.data.deribit')
    loaders = import_module('option_chain_analytics.data.loaders')
    tardis = import_module('option_chain_analytics.data.tardis')

    assert callable(cboe.load_local_cboe_options_data)
    assert callable(deribit.load_local_deribit_contract_ts_data)
    assert callable(tardis.load_local_tardis_contract_ts_data)
    assert callable(tardis.load_local_tardis_eod_options_data)
    assert callable(loaders.ts_data_loader_wrapper)


@pytest.mark.parametrize(
    'module_name',
    [
        'option_chain_analytics.chain_loader_from_ts',
        'option_chain_analytics.chain_ts',
        'option_chain_analytics.config',
        'option_chain_analytics.data.chain_loader_from_ts',
        'option_chain_analytics.data.chain_ts',
        'option_chain_analytics.data.ccxt_api',
        'option_chain_analytics.data.apis.ccxt_api',
        'option_chain_analytics.data.config',
        'option_chain_analytics.fitters',
        'option_chain_analytics.fitters.forward_discount',
        'option_chain_analytics.ts_loaders',
    ],
)
def test_deprecated_module_paths_are_removed(module_name: str) -> None:
    """OCA 5.0 does not retain the historical module-path compatibility layer."""
    with pytest.raises(ModuleNotFoundError):
        import_module(module_name)
