import pandas as pd
import matplotlib.pyplot as plt
import qis
from enum import Enum

# analytics
from option_chain_analytics import (OptionsDataDFs,
                                    create_chain_from_from_options_dfs,
                                    plot_slice_vols,
                                    plot_slice_open_interest,
                                    run_chain_report, local_path as local_path)
from option_chain_analytics.ts_loaders import ts_data_loader_wrapper, DataSource


class UnitTests(Enum):
    PRINT_CHAIN_DATA = 1
    PLOT_SLICE_DATA = 2
    RUN_CHAIN_REPORT = 3


def run_unit_test(unit_test: UnitTests):

    pd.set_option('display.max_rows', 500)
    pd.set_option('display.max_columns', 500)
    pd.set_option('display.width', 1000)

    ticker = 'BTC'  # BTC, ETH
    # value_time = pd.Timestamp('2023-10-01 08:00:00+00:00')
    value_time = pd.Timestamp('2023-10-01 08:00:00+00:00')

    options_data_dfs = OptionsDataDFs(**ts_data_loader_wrapper(ticker=ticker, data_source=DataSource.TARDIS_LOCAL))
    chain = create_chain_from_from_options_dfs(options_data_dfs=options_data_dfs, value_time=value_time)

    if unit_test == UnitTests.PRINT_CHAIN_DATA:
        for expiry, eslice in chain.expiry_slices.items():
            eslice.print()

    elif unit_test == UnitTests.PLOT_SLICE_DATA:
        eslice = chain.expiry_slices['31MAR23']
        plot_slice_vols(eslice=eslice)
        plot_slice_open_interest(eslice=eslice)

    elif unit_test == UnitTests.RUN_CHAIN_REPORT:
        figs = run_chain_report(chain=chain)
        qis.save_figs_to_pdf(figs=figs,
                             file_name=f"chain_report_{value_time:%Y%m%dT%H%M%S}",
                             orientation='landscape',
                             local_path=local_path.get_output_path())

    plt.show()


if __name__ == '__main__':

    unit_test = UnitTests.RUN_CHAIN_REPORT

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
