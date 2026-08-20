"""Small compatibility dispatcher across OCA's provider-specific adapters.

New code should normally import the owning provider module directly—for example
``option_chain_analytics.data.cboe`` for SPX/VIX data. ``DataSource`` and
``ts_data_loader_wrapper`` remain available at the package root for downstream
research code that selects a feed at runtime.

The dispatcher performs lazy imports. Importing the OCA package therefore does
not initialize an authenticated client, access the network, or require optional
provider libraries. Every successful branch returns keyword arguments accepted
by :class:`~option_chain_analytics.option_data.OptionsDataDFs`.
"""

from enum import Enum
from typing import Any, Dict

import pandas as pd


class DataSource(Enum):
    """Select a provider adapter for :func:`ts_data_loader_wrapper`.

    ``TARDIS_LOCAL`` and ``DERIBIT_LOCAL`` load existing local histories;
    ``CBOE_LOCAL`` loads SPX or VIX fitted-chain files or their normalized cache;
    ``THETADATA_EOD`` invokes the optional authenticated EOD adapter; and
    ``TARDIS_EOD_LOCAL`` reads the standardized exact-time daily cache.
    """

    TARDIS_LOCAL = 1
    DERIBIT_LOCAL = 2
    CBOE_LOCAL = 3
    THETADATA_EOD = 4
    TARDIS_EOD_LOCAL = 5


def ts_data_loader_wrapper(data_source: DataSource = DataSource.TARDIS_LOCAL,
                           ticker: str = 'BTC',
                           **kwargs
                           ) -> Dict[str, Any]:
    """Dispatch one provider request into ``OptionsDataDFs`` constructor inputs.

    Parameters
    ----------
    data_source : DataSource, default DataSource.TARDIS_LOCAL
        Provider adapter selected for this request.
    ticker : str, default 'BTC'
        Provider symbol or option root.
    **kwargs
        Provider-specific arguments forwarded unchanged to the selected loader,
        such as date bounds, cache paths, expirations, or an injected client.

    Returns
    -------
    dict[str, Any]
        ``chain_ts``, aligned ``spot_data``, and ``ticker`` suitable for
        ``OptionsDataDFs(**result)``.

    Raises
    ------
    NotImplementedError
        If ``data_source`` is not a supported ``DataSource`` member.

    See Also
    --------
    option_chain_analytics.data.cboe.load_local_cboe_options_data
    option_chain_analytics.data.tardis.load_local_tardis_eod_options_data
    option_chain_analytics.data.thetadata.load_thetadata_eod_options_data
    """
    if data_source == DataSource.TARDIS_LOCAL:
        from option_chain_analytics.data.tardis import load_local_tardis_contract_ts_data

        return load_local_tardis_contract_ts_data(ticker=ticker, **kwargs)

    if data_source == DataSource.DERIBIT_LOCAL:
        from option_chain_analytics.data.deribit import load_local_deribit_contract_ts_data

        return load_local_deribit_contract_ts_data(ticker=ticker, **kwargs)

    if data_source == DataSource.CBOE_LOCAL:
        from option_chain_analytics.data.cboe import load_local_cboe_options_data

        return load_local_cboe_options_data(ticker=ticker, **kwargs)

    if data_source == DataSource.THETADATA_EOD:
        from option_chain_analytics.data.thetadata import load_thetadata_eod_options_data

        return load_thetadata_eod_options_data(ticker=ticker, **kwargs)

    if data_source == DataSource.TARDIS_EOD_LOCAL:
        from option_chain_analytics.data.tardis import load_local_tardis_eod_options_data

        return load_local_tardis_eod_options_data(ticker=ticker, **kwargs)

    raise NotImplementedError(f'{data_source}')


class UnitTests(Enum):
    """Runnable local loader diagnostic cases."""

    LOAD_TARDIS_OPTIONS_DF = 1
    LOAD_DERIBIT_OPTIONS_DF = 2


def run_unit_test(unit_test: UnitTests):
    """Run the selected local Tardis or Deribit loader diagnostic."""
    from option_chain_analytics.data.deribit import load_local_deribit_contract_ts_data
    from option_chain_analytics.data.tardis import load_local_tardis_contract_ts_data
    from option_chain_analytics.option_data import OptionsDataDFs

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
