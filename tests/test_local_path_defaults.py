"""Regression tests for centralized local-drive path defaults.

Provider modules and repository examples must derive their default directories
from ``option_chain_analytics.local_path``. Provider-specific environment
variables such as the retired ``OCA_CBOE_PATH`` must not bypass that contract.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from option_chain_analytics import local_path as lp
from option_chain_analytics.ts_loaders import (
    CBOE_FILES_LOCAL_PATH,
    DERIBIT_LOCAL_PATH,
    TARDIS_FILES_LOCAL_PATH,
)


def _load_example(file_name: str) -> ModuleType:
    """Load one repository example as a module without executing its CLI."""
    file_path = Path(__file__).resolve().parents[1].joinpath('examples', file_name)
    spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot load example module from {file_path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provider_defaults_derive_from_central_resource_path() -> None:
    """Provider constants append their subdirectory to the shared resource path."""
    resource_path = lp.get_resource_path()
    assert CBOE_FILES_LOCAL_PATH == f'{resource_path}cboe_options\\'
    assert TARDIS_FILES_LOCAL_PATH == f'{resource_path}tardis\\'
    assert DERIBIT_LOCAL_PATH == f'{resource_path}deribit\\'


def test_cache_build_examples_derive_defaults_from_central_resource_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache CLIs use the shared resource path and ignore retired overrides."""
    monkeypatch.setenv('OCA_CBOE_PATH', 'retired-provider-specific-override')
    resource_path = lp.get_resource_path()
    cboe_example = _load_example('build_cboe_options_caches.py')
    combined_example = _load_example('build_local_options_caches.py')

    assert cboe_example.CBOE_LOCAL_PATH == f'{resource_path}cboe_options\\'
    assert combined_example.CBOE_LOCAL_PATH == f'{resource_path}cboe_options\\'
    assert combined_example.TARDIS_LOCAL_PATH == f'{resource_path}tardis\\'
    assert cboe_example._build_parser().get_default('data_dir') == Path(
        cboe_example.CBOE_LOCAL_PATH
    )
