"""Inspect option-chain slices and their volatility/open-interest plots."""

from enum import Enum

import matplotlib.pyplot as plt
import pandas as pd

from option_chain_analytics.data.loaders import DataSource, ts_data_loader_wrapper
from option_chain_analytics.option_data import OptionsDataDFs
from option_chain_analytics.reconstruction import create_chain_at_time
from option_chain_analytics.visuals.slices import (
    plot_slice_open_interest,
    plot_slice_vols,
    plot_slice_vols_with_oi,
)


class Locals(Enum):
    """Available option-slice development diagnostics."""

    PRINT_CHAIN_DATA = 1
    PLOT_SLICE_OI = 2
    PLOT_SLICE_VOL = 3
    PLOT_SLICE_VOL_OI = 4


def run_local(local: Locals) -> None:
    """Run the selected option-slice development diagnostic."""
    pd.set_option('display.max_rows', 500)
    pd.set_option('display.max_columns', 500)
    pd.set_option('display.width', 1000)

    ticker = 'ETH'
    value_time = pd.Timestamp('2023-02-07 08:00:00+00:00')
    slice_id = '31MAR23'

    options_data_dfs = OptionsDataDFs(
        **ts_data_loader_wrapper(ticker=ticker, data_source=DataSource.TARDIS_LOCAL)
    )
    chain = create_chain_at_time(options_data=options_data_dfs, value_time=value_time)
    chain.print_slices_id()

    if local == Locals.PRINT_CHAIN_DATA:
        for eslice in chain.expiry_slices.values():
            eslice.print()

    elif local == Locals.PLOT_SLICE_OI:
        eslice = chain.expiry_slices[slice_id]
        plot_slice_open_interest(eslice=eslice)

    elif local == Locals.PLOT_SLICE_VOL:
        eslice = chain.expiry_slices[slice_id]
        plot_slice_vols(eslice=eslice)
        plot_slice_vols(eslice=eslice, is_delta_space=True)

    elif local == Locals.PLOT_SLICE_VOL_OI:
        eslice = chain.expiry_slices[slice_id]
        plot_slice_vols_with_oi(
            eslice=eslice,
            is_delta_space=False,
            delta_bounds=(-0.1, 0.1),
        )

    manager = plt.get_current_fig_manager()
    manager.window.showMaximized()
    plt.show()


if __name__ == '__main__':
    run_local(local=Locals.PLOT_SLICE_VOL)
