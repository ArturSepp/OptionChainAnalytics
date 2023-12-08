import pandas as pd
import numpy as np
import yfinance as yf
import qis
from typing import List, Dict, Any, Literal, Tuple
from enum import Enum

# internal
import option_chain_analytics.pricers.bsm as bsm

# prop
from option_chain_analytics.data.config import TIME_FMT, compute_time_to_maturity
from option_chain_analytics.option_chain import SliceColumn

from option_chain_analytics import local_path as local_path

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
                                  value_time: pd.Timestamp = pd.Timestamp.utcnow()
                                  ) -> pd.DataFrame:
    asset = yf.Ticker(ticker)
    hist = asset.history(period="1d", interval="1m")
    current_price = hist['Close'][-1]

    # for the rate use 13w bill ticker ^IRX
    rhist = yf.Ticker('^IRX').history(period="2d", interval="1m")
    discount_rate = rhist['Close'][-1] / 100.0

    def infer_forward_discount(call0: float, call1: float, put0: float, put1: float, strike0: float, strike1: float):
        discount = - ((call0 - put0) - (call1 - put1)) / (strike0 - strike1)
        forward = 0.5 * ((call0 - put0) + (call1 - put1)) / discount + 0.5 * (strike0 + strike1)
        return forward, discount

    # imply forwards
    def imply_forwards(calls: pd.DataFrame, puts: pd.DataFrame, ttm: float, last_forward: float,
                       last_discfactor: float,
                       widths: float = 0.05
                       ) -> Tuple[float, float]:
        joint_strikes = list(set(calls.index.to_list()) & set(puts.index.to_list()))
        cond = np.logical_and(np.greater(joint_strikes, (1.0-widths) * last_forward),
                              np.less(joint_strikes, (1.0+widths) * last_forward))
        if len(joint_strikes) == 0:
            return np.nan
        atm_strikes = pd.Series(joint_strikes, index=joint_strikes).where(cond)
        atm_strikes = atm_strikes.dropna()
        calls = calls.loc[atm_strikes, :]  # alighn
        puts = puts.loc[atm_strikes, :]  # alighn
        strikes = atm_strikes.to_numpy()
        ask_call, bid_call = calls['ask'].to_numpy(), calls['bid'].to_numpy()
        ask_put, bid_put = puts['ask'].to_numpy(), puts['bid'].to_numpy()

        mid_call = 0.5*(ask_call + bid_call)
        mid_put = 0.5*(ask_put + bid_put)

         # find the spread
        spread = mid_put - mid_call
        idx = np.where(np.diff(np.sign(spread)) != 0)[0] + 1
        idx = idx[0]
        forward, discount = infer_forward_discount(call0=mid_call[idx - 1], call1=mid_call[idx],
                                                   put0=mid_put[idx - 1], put1=mid_put[idx],
                                                   strike0=strikes[idx - 1], strike1=strikes[idx])

        return forward, discount

    all_options = []
    last_forward = current_price
    last_discfactor = None
    for expiry in asset.options:
        opt = asset.option_chain(expiry)
        calls, puts = opt.calls.set_index('strike', drop=False), opt.puts.set_index('strike', drop=False)
        if calls.empty or puts.empty:
            continue
        calls.index.name, puts.index.name = '', ''

        # ttm
        expiry_time = pd.Timestamp(expiry, tz='UTC').replace(hour=20)  # expire at 20.00 UTC time = 16.00 US local time
        ttm = compute_time_to_maturity(maturity_time=expiry_time, value_time=value_time)
        last_discfactor = last_discfactor or np.exp(-discount_rate * ttm)

        forward, discfactor = imply_forwards(calls=calls, puts=puts, last_forward=last_forward, last_discfactor=last_discfactor, ttm=ttm)

        discount_rate = - np.log(discfactor) / ttm
        last_forward = forward
        last_discfactor = discfactor

        #if np.isnan(forward):  # try wider width
        #    raise ValueError(f"no forward")

        # option vol
        calls, puts = opt.calls.set_index('contractSymbol'), opt.puts.set_index('contractSymbol')

        # bid-ask can be zero if outside hours
        calls_bid = calls['bid'].fillna(0.0).to_numpy()
        calls_ask = calls['ask'].fillna(0.0).to_numpy()
        calls_mark = np.where(np.logical_and(calls_bid > 0.0, calls_ask > 0.0), 0.5*(calls_bid+calls_ask),
                              np.where(calls_bid > 0.0, calls_bid, calls_ask))
        calls[SliceColumn.MARK_PRICE.value] = calls_mark

        puts_bid = puts['bid'].fillna(0.0).to_numpy()
        puts_ask = puts['ask'].fillna(0.0).to_numpy()
        puts_mark = np.where(np.logical_and(puts_bid > 0.0, puts_ask > 0.0), 0.5*(puts_bid+puts_ask),
                             np.where(puts_bid > 0.0, puts_bid, puts_ask))
        puts[SliceColumn.MARK_PRICE.value] = puts_mark

        calls[SliceColumn.BID_IV.value] = bsm.infer_bsm_ivols_from_model_slice_prices(ttm=ttm, forward=forward,
                                                                                      strikes=calls['strike'].to_numpy(),
                                                                                      optiontypes=np.full(calls.index.shape, 'C'),
                                                                                      model_prices=calls_bid,
                                                                                      discfactor=discfactor)
        calls[SliceColumn.ASK_IV.value] = bsm.infer_bsm_ivols_from_model_slice_prices(ttm=ttm, forward=forward,
                                                                                      strikes=calls['strike'].to_numpy(),
                                                                                      optiontypes=np.full(calls.index.shape, 'C'),
                                                                                      model_prices=calls_ask,
                                                                                      discfactor=discfactor)
        calls[SliceColumn.MARK_IV.value] = bsm.infer_bsm_ivols_from_model_slice_prices(ttm=ttm, forward=forward,
                                                                                       strikes=calls['strike'].to_numpy(),
                                                                                       optiontypes=np.full(calls.index.shape, 'C'),
                                                                                       model_prices=calls_mark,
                                                                                       discfactor=discfactor)
        puts[SliceColumn.BID_IV.value] = bsm.infer_bsm_ivols_from_model_slice_prices(ttm=ttm, forward=forward,
                                                                                     strikes=puts['strike'].to_numpy(),
                                                                                     optiontypes=np.full(puts.index.shape, 'P'),
                                                                                     model_prices=puts_bid,
                                                                                     discfactor=discfactor)
        puts[SliceColumn.ASK_IV.value] = bsm.infer_bsm_ivols_from_model_slice_prices(ttm=ttm, forward=forward,
                                                                                     strikes=puts['strike'].to_numpy(),
                                                                                     optiontypes=np.full(puts.index.shape, 'P'),
                                                                                     model_prices=puts_ask,
                                                                                     discfactor=discfactor)
        puts[SliceColumn.MARK_IV.value] = bsm.infer_bsm_ivols_from_model_slice_prices(ttm=ttm, forward=forward,
                                                                                      strikes=puts['strike'].to_numpy(),
                                                                                      optiontypes=np.full(puts.index.shape, 'P'),
                                                                                      model_prices=puts_mark,
                                                                                      discfactor=discfactor)

        calls[SliceColumn.OPTION_TYPE.value] = 'C'
        puts[SliceColumn.OPTION_TYPE.value] = 'P'
        option_df = pd.concat([calls, puts], axis=0)

        # enter extra data
        option_df[SliceColumn.UNDERLYING_PRICE.value] = forward
        option_df[SliceColumn.CONTRACT.value] = option_df.index.to_list()

        option_df = option_df.rename({'bid': SliceColumn.BID_PRICE.value,
                                      'ask': SliceColumn.ASK_PRICE.value,
                                      'openInterest': SliceColumn.OPEN_INTEREST.value,
                                      'volume': SliceColumn.VOLUME.value,
                                      'strike': SliceColumn.STRIKE.value}, axis=1)

        option_df[SliceColumn.EXPIRY.value] = expiry_time
        option_df[SliceColumn.TTM.value] = ttm

        if isinstance(discount_rate, np.ndarray):
            discount_rate = discount_rate[0]
        option_df[SliceColumn.INTEREST_RATE.value] = discount_rate

        option_df = option_df.drop(['lastTradeDate', 'lastPrice', 'change', 'percentChange', 'impliedVolatility',
                                    'inTheMoney', 'contractSize', 'currency'], axis=1)

        # add greeks
        strike = option_df[SliceColumn.STRIKE.value].to_numpy()
        vol = option_df[SliceColumn.MARK_IV.value].to_numpy()
        optiontype = option_df[SliceColumn.OPTION_TYPE.value].to_numpy()
        option_df[SliceColumn.DELTA.value] = bsm.compute_bsm_vanilla_delta_vector(forward=forward, ttm=ttm, strike=strike, vol=vol,
                                                     optiontype=optiontype, discfactor=discfactor)
        option_df[SliceColumn.VEGA.value] = bsm.compute_bsm_vanilla_vega_vector(forward=forward, ttm=ttm, strike=strike, vol=vol)
        option_df[SliceColumn.THETA.value] = bsm.compute_bsm_vanilla_theta_vector(forward=forward, ttm=ttm, strike=strike, vol=vol,
                                                     optiontype=optiontype, discfactor=discfactor, discount_rate=discount_rate)
        option_df[SliceColumn.GAMMA.value] = bsm.compute_bsm_vanilla_gamma_vector(forward=forward, ttm=ttm, strike=strike, vol=vol)

        all_options.append(option_df)
    df = pd.concat(all_options, axis=0)

    df[SliceColumn.MATURITY_ID.value] = df[SliceColumn.EXPIRY.value].apply(lambda x: x.strftime('%d%b%Y'))
    df[SliceColumn.USD_MULTIPLIER.value] = 1.0
    df[SliceColumn.CONTRACT.value] = df.index
    df[SliceColumn.EXCHANGE_TIME.value] = value_time
    df[SliceColumn.UNDERLYING_INDEX.value] = ticker
    df[SliceColumn.CONTRACT_SIZE.value] = 100.0
    df[SliceColumn.ASK_SIZE.value] = 1.0
    df[SliceColumn.BID_SIZE.value] = 1.0

    df = df.reset_index(drop=True)

    # make sure all columns in SliceColumn exist
    df = df[[x.value for x in SliceColumn]]

    return df


def update_options_data(tickers: List[str] = ("SPY", ), is_live_markets: bool = True) -> None:

    for ticker in tickers:
        if is_live_markets:
            value_time = pd.Timestamp.utcnow() - pd.Timedelta(minutes=20)
        else:  # yesterday close
            value_time = (pd.Timestamp.utcnow() - pd.Timedelta(days=1)).normalize().replace(hour=20)
        df = fetch_yahoo_options_live_data(ticker, value_time=value_time)
        # file_path = get_yahoo_local_file_path(current_time=value_time, ticker=ticker)
        # qis.save_df_to_csv(df=df, local_path=file_path)
        file_path = get_yahoo_appended_file_path(ticker=ticker)
        qis.append_df_to_feather(df=df, local_path=file_path, index_col=None, keep='last')

        print(f"Data saved for {ticker} at value_time={value_time}")


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
    stocks = ["TSLA", "AAPL", "AMZN", "META", "AMD"]
    # tickers = ["EEM"]
    tickers = etfs + stocks

    if unit_test == UnitTests.UPDATE_OPTIONS_DATA:
        tickers = ['SPY']
        update_options_data(tickers, is_live_markets=False)

    elif unit_test == UnitTests.UPDATE_HF_DATA:
        update_hf_data(tickers)

    elif unit_test == UnitTests.LOAD_OPTIONS_DATA:
        from option_chain_analytics.data.chain_ts import OptionsDataDFs
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
