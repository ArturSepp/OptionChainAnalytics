"""
use yahoo api to create option chain data frame with columns = SliceColumn
"""
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import yfinance as yf
import qis as qis
from typing import List, Dict, Any, Literal, Union
from enum import Enum
import vanilla_option_pricers as bsm

# internal
from option_chain_analytics.fitters.utils import plot_slice_fits
from option_chain_analytics.config import TIME_FMT, compute_time_to_maturity
from option_chain_analytics.option_chain import SliceColumn
from option_chain_analytics import local_path as local_path

from option_chain_analytics.fitters.qp_price_fitter import (WeightType,
                                                            fit_slice_mark_prices_implied_vols_with_qp_solver)

YAHOO_LOCAL_PATH = f"{local_path.get_resource_path()}\\yahoo_options\\"
YAHOO_HF_LOCAL_PATH = f"{local_path.get_resource_path()}\\yahoo_hf\\"


def get_yahoo_local_file_path(current_time: pd.Timestamp,
                              ticker: str = 'SPY',
                              local_path: str = YAHOO_LOCAL_PATH
                              ) -> str:
    file_path = f"{local_path}{ticker}_{current_time.strftime(TIME_FMT)}.csv"
    return file_path


def get_yahoo_appended_file_path(ticker: str = 'SPY',
                                 local_path: str = YAHOO_LOCAL_PATH
                                 ) -> str:
    file_path = f"{local_path}{ticker}_appended_options.feather"
    return file_path


def get_yahoo_hf_appended_file_path(ticker: str = 'SPY',
                                    interval: Literal['1d', '1h', '30m', '15m', '5m', '1m'] = '30m',
                                    local_path: str = YAHOO_HF_LOCAL_PATH
                                    ) -> str:
    file_path = f"{local_path}{ticker}_{interval}.feather"
    return file_path


def fetch_yahoo_options_live_data(ticker: str = 'SPY',
                                  value_time: pd.Timestamp = pd.Timestamp.utcnow(),
                                  is_joint_solver: bool = True,
                                  eps: float = 0.0001,
                                  verbose: bool = False,
                                  produce_fit_report: bool = True
                                  ) -> Union[pd.DataFrame, List[plt.Figure]]:

    # for the rate use 13w bill ticker ^IRX
    rhist = yf.Ticker('^IRX').history(period="2d", interval="1m")
    rf_discount_rate = rhist['Close'].iloc[-1] / 100.0

    asset = yf.Ticker(ticker)
    spot_price = asset.history(period="2d", interval="15m")['Close'].iloc[-1]  # option data is 15m delayed
    all_options = []
    figs = []
    for expiry in asset.options:
        print(f"expiry={expiry}")
        opt = asset.option_chain(expiry)
        # ttm
        expiry_time = pd.Timestamp(expiry, tz='UTC').replace(hour=20)  # expire at 20.00 UTC time = 16.00 US local time
        ttm = compute_time_to_maturity(maturity_time=expiry_time, value_time=value_time)
        calls, puts = opt.calls.set_index('strike', drop=False), opt.puts.set_index('strike', drop=False)
        # calls, puts = opt.calls.set_index('contractSymbol'), opt.puts.set_index('contractSymbol')
        if calls.empty or puts.empty:
            continue
        calls.index.name, puts.index.name = '', ''
        # add type
        calls[SliceColumn.OPTION_TYPE.value] = 'C'
        puts[SliceColumn.OPTION_TYPE.value] = 'P'
        # rename
        calls = calls.rename({'bid': SliceColumn.BID_PRICE.value, 'ask': SliceColumn.ASK_PRICE.value}, axis=1)
        puts = puts.rename({'bid': SliceColumn.BID_PRICE.value, 'ask': SliceColumn.ASK_PRICE.value}, axis=1)

        # create slice df with necessary inputs
        slice_df = pd.concat([calls, puts], axis=0)
        slice_df = slice_df.set_index('strike', drop=False).sort_index()
        slice_df[SliceColumn.TTM.value] = ttm
        slice_df[SliceColumn.SPOT_PRICE.value] = spot_price

        slice_fit_outputs = fit_slice_mark_prices_implied_vols_with_qp_solver(slice_df=slice_df,
                                                                              is_joint_solver=is_joint_solver,
                                                                              eps=eps,
                                                                              verbose=verbose)

        # pasre outputs
        calls[SliceColumn.MARK_PRICE.value] = slice_fit_outputs.call_mark_prices
        calls[SliceColumn.BID_IV.value] = slice_fit_outputs.calls_bid_iv
        calls[SliceColumn.ASK_IV.value] = slice_fit_outputs.calls_ask_iv
        calls[SliceColumn.MARK_IV.value] = slice_fit_outputs.calls_mark_iv

        puts[SliceColumn.MARK_PRICE.value] = slice_fit_outputs.put_mark_prices
        puts[SliceColumn.BID_IV.value] = slice_fit_outputs.puts_bid_iv
        puts[SliceColumn.BID_IV.value] = slice_fit_outputs.puts_ask_iv
        puts[SliceColumn.MARK_IV.value] = puts[SliceColumn.BID_IV.value] = slice_fit_outputs.puts_mark_iv

        option_df = pd.concat([calls, puts], axis=0)

        # enter extra data
        forward = slice_fit_outputs.forward
        discfactor = slice_fit_outputs.discfactor
        option_df[SliceColumn.SPOT_PRICE.value] = spot_price
        option_df[SliceColumn.FORWARD_PRICE.value] = forward
        option_df[SliceColumn.CONTRACT.value] = option_df.index.to_list()
        option_df[SliceColumn.EXPIRY.value] = expiry_time
        option_df[SliceColumn.TTM.value] = ttm
        discount_rate = - np.log(slice_fit_outputs.discfactor) / ttm
        if isinstance(discount_rate, np.ndarray):
            discount_rate = discount_rate[0]
        option_df[SliceColumn.DISCOUNT.value] = slice_fit_outputs.discfactor

        option_df = option_df.rename({'openInterest': SliceColumn.OPEN_INTEREST.value,
                                      'volume': SliceColumn.VOLUME.value,
                                      'strike': SliceColumn.STRIKE.value}, axis=1)
        option_df = option_df.drop(['lastTradeDate', 'lastPrice', 'change', 'percentChange', 'impliedVolatility',
                                    'inTheMoney', 'contractSize', 'currency'], axis=1)

        # add greeks
        strike = option_df[SliceColumn.STRIKE.value].to_numpy()
        vol = option_df[SliceColumn.MARK_IV.value].to_numpy()
        optiontype = option_df[SliceColumn.OPTION_TYPE.value].to_numpy()
        option_df[SliceColumn.DELTA.value] = bsm.compute_bsm_vanilla_delta_vector(forward=forward, ttm=ttm, strike=strike,
                                                                                  vol=vol,
                                                                                  optiontype=optiontype, discfactor=discfactor)
        option_df[SliceColumn.VEGA.value] = bsm.compute_bsm_vanilla_vega_vector(forward=forward, ttm=ttm, strike=strike, vol=vol)
        option_df[SliceColumn.THETA.value] = bsm.compute_bsm_vanilla_theta_vector(forward=forward, ttm=ttm, strike=strike,
                                                                                  vol=vol,
                                                                                  optiontype=optiontype, discfactor=discfactor,
                                                                                  discount_rate=discount_rate)
        option_df[SliceColumn.GAMMA.value] = bsm.compute_bsm_vanilla_gamma_vector(forward=forward, ttm=ttm, strike=strike, vol=vol)

        all_options.append(option_df)

        if produce_fit_report:
            fig = plot_slice_fits(slice_df=slice_df, slice_fit_outputs=slice_fit_outputs, expiry=expiry)
            figs.append(fig)

    df = pd.concat(all_options, axis=0)
    df[SliceColumn.MATURITY_ID.value] = df[SliceColumn.EXPIRY.value].apply(lambda x: x.strftime('%d%b%Y'))
    df[SliceColumn.USD_MULTIPLIER.value] = 1.0
    df[SliceColumn.CONTRACT.value] = df.index
    df[SliceColumn.EXCHANGE_TIME.value] = value_time
    df[SliceColumn.UNDERLYING_INDEX.value] = ticker
    df[SliceColumn.CONTRACT_SIZE.value] = 100.0
    df[SliceColumn.ASK_SIZE.value] = 1.0  # dummies
    df[SliceColumn.BID_SIZE.value] = 1.0  # dummies

    df = df.reset_index(drop=True)

    # make sure all columns in SliceColumn exist
    for x in SliceColumn:
        if x.value not in df.columns:
            df[x.value] = np.nan
    # arrange order
    df = df[[x.value for x in SliceColumn]]

    return df, figs


def update_options_data(tickers: List[str] = ("SPY", ),
                        eps: float = 0.0001,
                        is_live_markets: bool = True,
                        produce_fit_report: bool = True
                        ) -> None:

    for ticker in tickers:
        try:
            if is_live_markets:
                value_time = pd.Timestamp.utcnow() - pd.Timedelta(minutes=20)
            else:  # yesterday close
                raise NotImplementedError
                # value_time = (pd.Timestamp.utcnow() - pd.Timedelta(days=1)).normalize().replace(hour=20)
            df, figs = fetch_yahoo_options_live_data(ticker, value_time=value_time, produce_fit_report=produce_fit_report,
                                                     eps=eps)
        except:
            print(f"failed to fetch data for {ticker}")
            continue

        if produce_fit_report:
            file_name = f"{ticker}_{value_time.strftime(TIME_FMT)}"
            qis.save_figs_to_pdf(figs=figs, file_name=file_name, local_path=YAHOO_LOCAL_PATH)

        # save the current snapshot to csv
        file_path = get_yahoo_local_file_path(current_time=value_time, ticker=ticker)
        qis.save_df_to_csv(df=df, local_path=file_path)
        print(f"Data snapshot created for {ticker} at value_time={value_time} with path={file_path}")

        # append the current snapshot to feather
        file_path = get_yahoo_appended_file_path(ticker=ticker)
        qis.append_df_to_feather(df=df, local_path=file_path, index_col=None, keep='last')
        print(f"Data appended for {ticker} at value_time={value_time} with path={file_path}")


def fetch_hf_ohlc(ticker: str = 'SPY',
                  interval: Literal['1d', '1h', '30m', '15m', '5m', '1m'] = '30m'
                  ) -> pd.DataFrame:
    """
    fetch hf data using yf
    for m and h frequencies we shift the data forward because yf
    reports timestamps of bars at the start of the period: we shift it to the end of the period
    """
    asset = yf.Ticker(ticker)
    if interval == '1d':  # close to close
        # ohlc_data = asset.history(period="730d", interval='1d')
        ohlc_data = yf.download(tickers=ticker, start=None, end=None, ignore_tz=True)
        ohlc_data.index = ohlc_data.index.tz_localize('UTC')
    elif interval == '1h':
        ohlc_data = asset.history(period="730d", interval="1h")
        ohlc_data.index = [t + pd.Timedelta(minutes=60) for t in ohlc_data.index]
    elif interval == '30m':
        ohlc_data = asset.history(period="60d", interval="30m")
        ohlc_data.index = [t + pd.Timedelta(minutes=30) for t in ohlc_data.index]
    elif interval == '15m':
        ohlc_data = asset.history(period="60d", interval="15m")
        ohlc_data.index = [t + pd.Timedelta(minutes=15) for t in ohlc_data.index]
    elif interval == '5m':
        ohlc_data = asset.history(period="60d", interval="5m")
        ohlc_data.index = [t + pd.Timedelta(minutes=5) for t in ohlc_data.index]
    elif interval == '1m':
        ohlc_data = asset.history(period="7d", interval="1m")
        ohlc_data.index = [t + pd.Timedelta(minutes=1) for t in ohlc_data.index]
    else:
        raise NotImplementedError(f"interval={interval}")
    ohlc_data = ohlc_data.rename({'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close'}, axis=1)
    ohlc_data.index = ohlc_data.index.tz_convert('UTC')
    ohlc_data.index.name = 'timestamp'
    return ohlc_data


def update_hf_data(tickers: List[str] = ("SPY", ),
                   intervals: List[str] = ['1d', '1h', '30m', '15m', '5m', '1m']
                   ):
    for ticker in tickers:
        for interval in intervals:
            df = fetch_hf_ohlc(ticker=ticker, interval=interval)
            file_path = get_yahoo_hf_appended_file_path(ticker=ticker, interval=interval)
            qis.append_df_to_feather(df=df, local_path=file_path, index_col='timestamp')


def load_contract_ts_data(ticker: str = 'SPY',
                          local_path: str = YAHOO_LOCAL_PATH
                          ) -> Dict[str, Any]:

    file_path = get_yahoo_appended_file_path(ticker=ticker, local_path=local_path)
    chain_ts = qis.load_df_from_feather(local_path=file_path, index_col=None)
    # spot_data = qis.load_df_from_feather(file_name=f"{ticker}_perp_data", local_path=f"{lp.get_resource_path()}\\tardis\\")
    return dict(chain_ts=chain_ts, spot_data=None, ticker=ticker)


class UnitTests(Enum):
    UPDATE_OPTIONS_DATA = 1
    UPDATE_HF_DATA = 2
    LOAD_OPTIONS_DATA = 3


def run_unit_test(unit_test: UnitTests):

    etfs = ["SPY", "QQQ", "IWM", "HYG", "^VIX", "VXX", "EEM", "SQQQ", "TQQQ", "GLD", "USO", "TLT", "USO"]
    stocks = ["TSLA", "AAPL", "AMZN", "META", "NVDA"]
    # tickers = ["EEM"]
    tickers = etfs + stocks

    if unit_test == UnitTests.UPDATE_OPTIONS_DATA:
        # tickers = ['HYG']
        update_options_data(tickers, is_live_markets=True,
                            eps=0.001,
                    produce_fit_report=True)

    elif unit_test == UnitTests.UPDATE_HF_DATA:
        update_hf_data(tickers)

    elif unit_test == UnitTests.LOAD_OPTIONS_DATA:
        from option_chain_analytics.chain_ts import OptionsDataDFs
        options_data_dfs = OptionsDataDFs(**load_contract_ts_data(ticker='SPY'))
        options_data_dfs.print()
        time_index = options_data_dfs.get_timeindex()
        print(f"time_index={time_index}")


if __name__ == '__main__':

    unit_test = UnitTests.UPDATE_OPTIONS_DATA

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
