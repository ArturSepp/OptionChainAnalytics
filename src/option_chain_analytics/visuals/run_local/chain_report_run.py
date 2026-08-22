"""Build and save a local multi-expiry chain report."""

from enum import Enum

import matplotlib.pyplot as plt
import pandas as pd
import qis

from option_chain_analytics import local_path as lp
from option_chain_analytics.data.loaders import DataSource, ts_data_loader_wrapper
from option_chain_analytics.option_data import OptionsDataDFs
from option_chain_analytics.reconstruction import create_chain_at_time
from option_chain_analytics.visuals.chain_report import run_chain_report


class Locals(Enum):
    """Available chain-report development diagnostics."""

    RUN_CHAIN_REPORT = 1


def run_local(local: Locals) -> None:
    """Build and save the selected local chain-report case."""
    ticker = 'BTC'
    options_data_dfs = OptionsDataDFs(
        **ts_data_loader_wrapper(ticker=ticker, data_source=DataSource.TARDIS_LOCAL)
    )

    if local == Locals.RUN_CHAIN_REPORT:
        value_time = pd.Timestamp('2023-02-06 08:00:00+00:00')
        chain = create_chain_at_time(options_data=options_data_dfs, value_time=value_time)
        figs = run_chain_report(chain=chain)

        qis.save_figs_to_pdf(
            figs=figs,
            file_name=f'chain_report_{value_time:%Y%m%dT%H%M%S}',
            orientation='landscape',
            local_path=lp.get_output_path(),
        )

    plt.show()


if __name__ == '__main__':
    run_local(local=Locals.RUN_CHAIN_REPORT)
