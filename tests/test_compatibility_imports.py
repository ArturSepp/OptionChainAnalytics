from option_chain_analytics import (
    NearestStrikeOnGrid as PublicNearestStrikeOnGrid,
)
from option_chain_analytics import (
    OptionsDataDFs as PublicOptionsDataDFs,
)
from option_chain_analytics import (
    create_chain_from_from_options_dfs as public_create_chain,
)
from option_chain_analytics.data.chain_loader_from_ts import (
    create_chain_from_from_options_dfs as compatibility_create_chain,
)
from option_chain_analytics.data.chain_ts import OptionsDataDFs as CompatibilityOptionsDataDFs
from option_chain_analytics.data.config import NearestStrikeOnGrid as CompatibilityNearestStrikeOnGrid


def test_historical_data_module_imports_resolve_to_public_symbols() -> None:
    assert CompatibilityOptionsDataDFs is PublicOptionsDataDFs
    assert CompatibilityNearestStrikeOnGrid is PublicNearestStrikeOnGrid
    assert compatibility_create_chain is public_create_chain
