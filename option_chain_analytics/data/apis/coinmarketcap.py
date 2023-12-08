import time
import pandas as pd
import numpy as np
from typing import List, Optional, Union
from enum import Enum
from cryptocmd import CmcScraper


def fetch_instrument_data(ticker: str = 'btc',
                          time_str: str = 'timestamp'
                          ) -> pd.DataFrame:
    """
    fetch using cmc scarpper
    """
    if ticker is None:
        raise TypeError(f"ticker is none")

    scraper = CmcScraper(coin_code=ticker, all_time=True, order_ascending=True)

    try:
        data = scraper.get_dataframe()
    except TypeError:
        print(f"no data for ticker = {ticker}")
        return pd.DataFrame()

    data['Date'] = pd.to_datetime(data['Date'])
    data = data.set_index('Date', drop=True)
    data.index = data.index.normalize()  #remove seconds info
    data.index.name = time_str

    column_map = {'Close': 'close',
                  'Market Cap': 'market_cap',
                  'Volume': 'volume',
                  'Open': 'open',
                  'High': 'high',
                  'Low': 'low'}
    data = data.rename(column_map, axis=1)
    data = data.replace({0.0: np.nan})

    return data


class UnitTests(Enum):
    DATA = 1


def run_unit_test(unit_test: UnitTests):

    import matplotlib.pyplot as plt

    if unit_test == UnitTests.DATA:
        ticker = 'USDC'
        data = fetch_instrument_data(ticker=ticker)
        print(data)
        data['market_cap'].plot()
        data['volume'].plot()

    plt.show()


if __name__ == '__main__':

    unit_test = UnitTests.DATA

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
