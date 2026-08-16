import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

import ccxt
import numpy as np
import pandas as pd


def get_supported_exchanges() -> List[str]:
    return ccxt.exchanges


def get_exchange(exchange: str = 'deribit') -> ccxt.Exchange:
    try:
        exchange = getattr(ccxt, exchange)()
    except AttributeError:
        raise KeyError(f"Exchange {exchange} not found")
    return exchange


def get_mid_price(exchange: str = 'binance', symbol: str = 'ETHUSDT') -> float:
    exchange = get_exchange(exchange=exchange)
    data = exchange.fetch_ticker(symbol=symbol)
    return 0.5*(data['bid']+data['ask'])


def get_available_instruments(exchange: str = 'deribit') -> Tuple[List[str], List[str]]:
    exchange = get_exchange(exchange=exchange)
    exchange.load_markets()
    return exchange.markets, exchange.markets_by_id


def fetch_symbol(exchange: str = 'okx', symbol: str = 'BTC-USDT-230331') -> Dict[str, Any]:
    exchange = get_exchange(exchange=exchange)
    return exchange.fetchTicker(symbol=symbol)


def fetch_ohlcv(symbols: List[str],
                exchange: str = 'deribit',
                freq: str = '1h',
                is_normalize_volume: bool = True
                ) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """
    returns open, high, low, close, volume
    Available timeframes are: 1m, 3m, 5m, 10m, 15m, 30m, 1h, 2h, 3h, 6h, 12h, 1d
    symbol = 'ETH-28JAN22' for deribit
    """
    if freq == 'H':
        freq = '1h'
    elif freq == 'D':
        freq = '1d'

    if exchange == 'huobi':
        limit = 2000
    elif exchange == 'bybit':
        limit = 200
    else:
        limit = 5000

    exchange = get_exchange(exchange=exchange)

    # Check if fetching of OHLC Data is supported
    if not exchange.has["fetchOHLCV"]:
        raise ValueError(f"{exchange} does not support fetching OHLC data")

    # Check requested timeframe is available
    if (not hasattr(exchange, 'timeframes')) or (freq not in exchange.timeframes):
        print(f"The requested timeframe {freq} is not available from {exchange}")
        print('Available timeframes are:')
        for key in exchange.timeframes.keys():
            print(key)
        raise ValueError

    dfs = {}
    columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']

    def process_data(data: pd.DataFrame) -> pd.DataFrame:
        df = pd.DataFrame(data, columns=columns)
        df[columns] = df[columns].apply(pd.to_numeric, errors='ignore')
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df = df.set_index('timestamp')
        return df

    for symbol in symbols:
        try:
            data = exchange.fetch_ohlcv(symbol=symbol, timeframe=freq, limit=limit) # params=dict(include_old=True)

        except (TypeError, ccxt.errors.BadSymbol):
            print(f"{symbol} not available on {exchange}, creating empty frame")
            df = pd.DataFrame(columns=columns).set_index('timestamp')

        else:
            df = process_data(data)
            if normalize_volume:
                df = normalize_volume(exchange=exchange, symbol=symbol, df=df)

        dfs[symbol] = df

    if len(symbols) == 1:
        dfs = dfs[symbols[0]]

    return dfs


def fetch_close_prices(symbols: List[str],
                       exchange: str = 'deribit',
                       freq: str = '1h'
                       ) -> pd.DataFrame:
    """
    returns open, high, low, close, volume
    Available timeframes are: 1m, 3m, 5m, 10m, 15m, 30m, 1h, 2h, 3h, 6h, 12h, 1d
    symbol = 'ETH-28JAN22' for deribit
    """
    df = {}
    for symbol in symbols:
        df[symbol] = fetch_ohlcv(symbols=[symbol], exchange=exchange, freq=freq)['close'].rename(symbol)
    df = pd.DataFrame.from_dict(df, orient='columns')
    return df


def fetch_ohlcv_with_last(symbols: List[str],
                          exchange: str = 'deribit',
                          freq: str = '1h',
                          last_timestamp: pd.Timestamp = None,  # to sync last stamp use common last_timestamp
                          use_bid_ask_for_last: bool = True
                          ) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """
    call fetch_ohlcv and add most recent timestamp
    """
    dfs = fetch_ohlcv(symbols=symbols, exchange=exchange, freq=freq, is_normalize_volume=False) # will be called with new pools
    exchange = get_exchange(exchange=exchange)
    for symbol in symbols:
        if last_timestamp is not None:
            try:
                data = exchange.fetch_ticker(symbol=symbol)
            except (TypeError, ccxt.errors.BadSymbol):
                print(f"{symbol} not available on {exchange}, no last is added")
                continue
            if use_bid_ask_for_last:
                if 'bid' and 'ask' in data.keys():
                    bid, ask = data['bid'], data['ask']
                    if bid is not None and ask is not None:
                        mid = 0.5*(bid+ask)
                    else:
                        mid = data['close']
                else:
                    mid = data['close']
                data_to_enter = np.array([data['open'], data['high'], data['low'], mid, data['baseVolume']])
            else:
                data_to_enter = np.array([data['open'], data['high'], data['low'], data['close'], data['baseVolume']])

            if isinstance(dfs, dict):
                dfs[symbol].loc[last_timestamp, :] = data_to_enter
            else:
                dfs.loc[last_timestamp, :] = data_to_enter

    if isinstance(dfs, dict):
        for symbol, df in dfs.items():
            dfs[symbol] = normalize_volume(exchange=exchange, symbol=symbol, df=df)
    else:
        dfs = normalize_volume(exchange=exchange, symbol=symbols[0], df=dfs)

    return dfs


def normalize_volume(exchange: ccxt.exchanges, symbol: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    normalize echange volume based on contract specs
    """
    if isinstance(exchange, ccxt.bybit):  # volumes to contract
        if bool(re.search(r'\d', symbol)):  # for termed future
            df['volume'] = df['volume'] / df['close']

    if isinstance(exchange, ccxt.okx):  # volumes to contract
        if bool(re.search(r'\d', symbol)):  # for termed future
            print(symbol)
            df['volume'] = df['volume'] * 0.01
    return df


def fetch_funding_rate(symbol: str = 'ETH/USDT:USDT',
                       exchange: str = 'binanceusdm',
                       freq: Optional[str] = 'H'
                       ) -> pd.Series:
    exchange = get_exchange(exchange)
    funding = exchange.fetch_funding_rate_history(symbol)
    df = pd.json_normalize(funding)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df = df.set_index('timestamp')
    if 'info.fundingRate' in df.columns:  # this is accurate to what is paid
        frate = df['info.fundingRate'].apply(pd.to_numeric, errors='ignore')
    else:
        frate = df['fundingRate'].apply(pd.to_numeric, errors='ignore')
    if freq is not None:
        frate = frate.resample('H').last()
    return frate


class UnitTests(Enum):
    EXCHANGES = 1
    PRICE_QUOTE = 2
    INSTRUMENTS = 3
    FETCH = 4
    FETCH_WITH_LAST = 5
    FUNDING_RATE = 6
    FETCH_TICKER = 7
    TEST = 8


def run_unit_test(unit_test: UnitTests):

    if unit_test == UnitTests.EXCHANGES:
        exchanges = get_supported_exchanges()
        for idx, exchange in enumerate(exchanges):
            print(f"{idx+1}: {exchange}")

    elif unit_test == UnitTests.PRICE_QUOTE:
        mid_price = get_mid_price(exchange='binance', symbol='ETHUSDT')
        print(mid_price)

    elif unit_test == UnitTests.INSTRUMENTS:
        markets, markets_by_id = get_available_instruments(exchange='binance')
        asset = 'BTC'
        print("########## markets############################")
        for idx, symbol in enumerate(markets):
            if asset in symbol:
                print(f"{idx+1}: {symbol}")
        print("########## markets_by_id  ############################")
        for idx, symbol in enumerate(markets_by_id):
            if asset in symbol:
                print(f"{idx+1}: {symbol}")

    elif unit_test == UnitTests.FETCH:
        # dfs = fetch_ohlcv(symbols=['ETH-PERPETUAL', 'ETH-31MAR23', 'ETH-30JUN23'], exchange='deribit', freq='H')
        # dfs = fetch_ohlcv(symbols=['ETHUSDH23', 'ETHUSDM23'], exchange='bybit', freq='H')
        # dfs = fetch_ohlcv(symbols=['ETH/USD:USDC', 'ETH/USD:ETH-230331', 'ETH/USD:ETH-230630'], exchange='bybit', freq='1h')
        # dfs = fetch_ohlcv(symbols=['ETH-USDT-SWAP', 'ETH-USDT-230224', 'ETH-USDT-230331'], exchange='okx', freq='1h')
        # dfs = fetch_ohlcv(symbols=['BTC-USDT-230331'], exchange='okx', freq='1h')
        # dfs = fetch_ohlcv(symbols=['ETH-USD', 'ETH230113', 'ETH230331'], exchange='huobi', freq='1h')
        # dfs = fetch_ohlcv(symbols=['BTCUSDT_230331'], exchange='binanceusdm', freq='1h')
        dfs = fetch_ohlcv(symbols=['BTCUSDT'], exchange='binance', freq='1h')
        # dfs = fetch_ohlcv(symbols=['ETHUSDT'], exchange='binanceusdm', freq='1h')

        print(dfs)
        for k, v in dfs.items():
            print(k)
            # print(v)
            print(v.rolling(24).sum())

    elif unit_test == UnitTests.FETCH_WITH_LAST:
        dfs = fetch_ohlcv_with_last(symbols=['ETH-USDT-230929'], exchange='okx', freq='1h')
        print(dfs)

    elif unit_test == UnitTests.FUNDING_RATE:
        #funding = fetch_funding_rate(ticker='ETHUSDT', exchange='binanceusdm')
        # funding = fetch_funding_rate(symbol='LOOKS/USDT', exchange='okx')
        funding = fetch_funding_rate(symbol='BTCUSDT', exchange='binanceusdm')
        #funding = fetch_funding_rate(symbol='FIS/USDT', exchange='gateio')
        print(funding)

    elif unit_test == UnitTests.FETCH_TICKER:
        data = fetch_symbol(exchange='okx', symbol='ETH-USDT-230331')
        print(data)
        data = fetch_symbol(exchange='binanceusdm', symbol='BTCUSDT_230331')
        print(data)

        exchange = get_exchange(exchange='binanceusdm')
        this = exchange.fetchOpenInterestHistory('BTCUSDT_230331')
        print(this)

        exchange = get_exchange(exchange='okx')
        this = exchange.fetchOpenInterestHistory('BTCUSDT_230331')
        print(this)

    elif unit_test == UnitTests.TEST:
        symbol = 'ETH-USDT-230929'
        exchange = 'okx'
        exchange = get_exchange(exchange=exchange)
        data = exchange.fetch_ticker(symbol=symbol)
        print(data)


if __name__ == '__main__':

    unit_test = UnitTests.FUNDING_RATE

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
