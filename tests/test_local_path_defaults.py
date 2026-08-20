"""Regression tests for centralized local-drive path defaults.

Provider modules must derive their default directories from
``option_chain_analytics.local_path``. Provider-specific environment variables
such as the retired ``OCA_CBOE_PATH`` must not bypass that contract.
"""

from pathlib import Path

import pytest

from option_chain_analytics import local_path as lp
from option_chain_analytics.data.cache import _normalized_cache_directory
from option_chain_analytics.data.cboe import (
    CBOE_CACHE_LOCAL_PATH,
    CBOE_FILES_LOCAL_PATH,
)
from option_chain_analytics.data.deribit import DERIBIT_LOCAL_PATH
from option_chain_analytics.data.tardis import (
    TARDIS_EOD_CACHE_LOCAL_PATH,
    TARDIS_FILES_LOCAL_PATH,
)


def test_provider_defaults_derive_from_central_resource_path() -> None:
    """Provider constants append their subdirectory to the shared resource path."""
    resource_path = lp.get_resource_path()
    assert CBOE_FILES_LOCAL_PATH == f'{resource_path}cboe_options\\'
    assert TARDIS_FILES_LOCAL_PATH == f'{resource_path}tardis\\'
    assert DERIBIT_LOCAL_PATH == f'{resource_path}deribit\\'


def test_normalized_cache_defaults_use_the_central_cache_path() -> None:
    """Default normalized caches are separate from raw provider archives."""
    cache_path = lp.get_cache_path()
    assert CBOE_CACHE_LOCAL_PATH == f'{cache_path}cboe_options\\'
    assert TARDIS_EOD_CACHE_LOCAL_PATH == f'{cache_path}tardis\\'
    assert _normalized_cache_directory(
        local_path=CBOE_FILES_LOCAL_PATH,
        default_source_path=CBOE_FILES_LOCAL_PATH,
        default_cache_path=CBOE_CACHE_LOCAL_PATH,
    ) == CBOE_CACHE_LOCAL_PATH
    assert _normalized_cache_directory(
        local_path='custom-provider-directory',
        default_source_path=CBOE_FILES_LOCAL_PATH,
        default_cache_path=CBOE_CACHE_LOCAL_PATH,
    ) == 'custom-provider-directory'


def test_cache_path_defaults_to_resources_and_supports_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The cache root has a repository default and one central override."""
    monkeypatch.delenv('OCA_CACHE_PATH', raising=False)
    assert Path(lp.get_cache_path()).name == 'resources'
    monkeypatch.setenv('OCA_CACHE_PATH', str(tmp_path))
    assert Path(lp.get_cache_path()) == tmp_path.resolve()
