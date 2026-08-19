"""Fetch and persist Bloomberg BVOL volatility-surface time series.

TODO: Map the bbg-fetch BVOL tenor/moneyness surface to synthetic option
prices, with a deterministic option-maturity roll convention, for tests and
visualisations. Until then, this module stores BVOL inputs under OCA's
centralized ``bbg_vols`` resource folder and does not present them as observed
option prices.
"""

from enum import Enum

import bbg_fetch as bbg
import qis as qis

from option_chain_analytics import local_path as lp

BBG_LOCAL_PATH = f"{lp.get_resource_path()}bbg_vols\\"
print(BBG_LOCAL_PATH)


class UnitTests(Enum):
    """Runnable local Bloomberg data cases."""

    CREATE_VOL_DATA = 1


def run_unit_test(unit_test: UnitTests):
    """Fetch and save the selected Bloomberg BVOL time-series case."""

    if unit_test == UnitTests.CREATE_VOL_DATA:
        ticker = 'SPX Index'
        df = bbg.fetch_vol_timeseries(ticker='SPX Index', vol_fields=bbg.IMPVOL_FIELDS_MNY)
        print(df)
        qis.save_df_to_csv(df=df, file_name=f"{ticker}_MNY", local_path=BBG_LOCAL_PATH)


if __name__ == '__main__':

    unit_test = UnitTests.CREATE_VOL_DATA

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
