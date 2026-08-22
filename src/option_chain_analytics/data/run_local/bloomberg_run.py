"""Fetch and persist a local Bloomberg BVOL volatility-surface time series."""

from enum import Enum

import bbg_fetch as bbg
import qis

from option_chain_analytics import local_path as lp

BBG_LOCAL_PATH = f"{lp.get_resource_path()}bbg_vols\\"


class Locals(Enum):
    """Available Bloomberg development diagnostics."""

    CREATE_VOL_DATA = 1


def run_local(local: Locals) -> None:
    """Fetch and save the selected Bloomberg BVOL time-series case."""
    if local == Locals.CREATE_VOL_DATA:
        ticker = 'SPX Index'
        print(BBG_LOCAL_PATH)
        df = bbg.fetch_vol_timeseries(ticker=ticker, vol_fields=bbg.IMPVOL_FIELDS_MNY)
        print(df)
        qis.save_df_to_csv(df=df, file_name=f"{ticker}_MNY", local_path=BBG_LOCAL_PATH)


if __name__ == '__main__':
    run_local(local=Locals.CREATE_VOL_DATA)
