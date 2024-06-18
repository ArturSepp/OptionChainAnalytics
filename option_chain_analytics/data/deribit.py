"""
fetch deribit data
"""
import qis
import requests
import pandas as pd
from typing import List, Literal
from enum import Enum
from tqdm import tqdm

# internal
from option_chain_analytics.option_chain import SliceColumn
from option_chain_analytics.config import TIME_FMT, compute_time_to_maturity

# local paths
from option_chain_analytics import local_path as lp

DERIBIT_LOCAL_PATH = f"{lp.get_resource_path()}\\deribit\\"


def get_deribit_local_file_path(current_time: pd.Timestamp,
                                ticker: Literal['BTC', 'ETH'] = 'ETH',
                                local_path: str = DERIBIT_LOCAL_PATH
                                ) -> str:
    file_path = f"{local_path}{ticker}_{current_time.strftime(TIME_FMT)}.csv"
    return file_path


def get_deribit_appended_file_path(ticker: Literal['BTC', 'ETH'] = 'ETH',
                                   local_path: str = DERIBIT_LOCAL_PATH
                                   ) -> str:
    file_path = f"{local_path}{ticker}_appended_options.feather"
    return file_path


class DeribitApi:
    """
    fetch all instruments data from deribit
    """
    def __init__(self, currency: Literal['BTC', 'ETH'] = 'BTC'):
        """
        implement as Data fetching from Deribit using api
        """
        self.url = 'https://www.deribit.com/api/v2/public/'
        self.currency = str.lower(currency)

    def get_live_instruments(self) -> pd.DataFrame:
        """
        This method is used to retrieve live instruments
        -------------
        df = api.get_live_instruments()
        df.columns = Index(['tick_size', 'taker_commission', 'strike', 'settlement_period',
       'settlement_currency', 'rfq', 'quote_currency', 'price_index',
       'option_type', 'min_trade_amount', 'maker_commission', 'kind',
       'is_active', 'instrument_name', 'instrument_id', 'expiration_timestamp',
       'creation_timestamp', 'counter_currency', 'contract_size',
       'block_trade_tick_size', 'block_trade_min_trade_amount',
       'block_trade_commission', 'base_currency', 'max_liquidation_commission',
       'max_leverage', 'future_type'],
        """
        data = {'currency': self.currency}
        df = None
        for attempt in range(10):  # tend to break on several request
            r = requests.get(f"{self.url}get_instruments", data).json()
            if 'result' in r.keys():
                df = pd.DataFrame(r['result'])
                break
            else:
                print(f"try attempt {attempt+1}: {r}")
        if df is None:
            raise ValueError(f"could not get data after 10 attempts")
        return df

    def get_instruments_urls(self) -> List[str]:
        """
         api.get_instruments_urls()
        ['https://www.deribit.com/api/v2/public/get_order_book?instrument_name=BTC-4SEP20-13250-P',
        'https://www.deribit.com/api/v2/public/get_order_book?instrument_name=BTC-26MAR21-8000-P',
        ....]
        """
        live_instruments = self.get_live_instruments()
        print(live_instruments)
        request_url = f"{self.url}get_order_book?instrument_name="
        url_storage = [f"{request_url}{instrument}" for instrument in live_instruments['instrument_name']]
        return url_storage

    def request_get(self, url) -> dict:
        """
        An intermediate function used in conjunction with the `collect_data` method.
        """
        out = None
        for attempt in range(10):  # tend to break on several request
            r = requests.get(url).json()
            if 'result' in r.keys():
                out = r['result']
                break
        if out is None:
            print(f"could not get data for {url} after 10 attempts")
        return out

    def fetch_live_data(self) -> pd.DataFrame:
        """
        Retrieves instrument data
        -------------
        df = data.collect_data()
        df.columns
        Index(['expiration_timestamp', 'option_type', 'instrument_name', 'strike',
               'underlying_price', 'underlying_index', 'timestamp', 'stats', 'state',
               'settlement_price', 'open_interest', 'min_price', 'max_price',
               'mark_price', 'mark_iv', 'last_price', 'interest_rate',
               'instrument_name', 'index_price', 'greeks', 'estimated_delivery_price',
               'change_id', 'bids', 'bid_iv', 'best_bid_price', 'best_bid_amount',
               'best_ask_price', 'best_ask_amount', 'asks', 'ask_iv'],
                dtype='object')
        """
        live_instruments = self.get_live_instruments().set_index('instrument_name')
        raw_data = []
        request_url = f"{self.url}get_order_book?instrument_name="
        for instrument in tqdm(live_instruments.index):
            url_instrument = f"{request_url}{instrument}"
            raw_data_ = self.request_get(url_instrument)
            if raw_data_ is not None:
                raw_data.append(raw_data_)
        df = pd.DataFrame(raw_data).set_index('instrument_name')

        # stats = pd.json_normalize(df['stats']).set_index(df.index)
        # print(stats)
        # df = pd.concat([df.drop('stats', axis=1), pd.json_normalize(df['stats'])], axis=1)
        # print(df)

        df_joint = pd.concat([df, live_instruments], axis=1)

        return df_joint


def parse_deribit_options_data(df: pd.DataFrame,
                               value_time: pd.Timestamp,
                               ticker: str
                               ) -> pd.DataFrame:
    """
    take deribit instruments df and produce df with SliceColumn for options data
    """
    # 1 get all options:
    option_df = df.loc[df['kind'] == 'option'].copy()
    option_df['expiry_time'] = [pd.to_datetime(x, unit='ms', utc=True) for x in option_df['expiration_timestamp']]
    option_df[SliceColumn.EXCHANGE_TIME.value] = value_time
    option_df['ttm'] = option_df.apply(lambda x: compute_time_to_maturity(x['expiry_time'], x[SliceColumn.EXCHANGE_TIME.value]), axis=1)

    # greeks string to dict and to pd.Dataframe
    greeks = pd.DataFrame.from_dict({key: x for key, x in zip(option_df.index, option_df['greeks'].to_numpy())}, orient='index')  #.apply(ast.literal_eval).to_dict()
    stats = pd.DataFrame.from_dict({key: x for key, x in zip(option_df.index, option_df['stats'].to_numpy())}, orient='index')
    # filter to include all columns
    new_options_df = pd.concat([pd.Series(option_df.index, index=option_df.index, name=SliceColumn.CONTRACT.value),
                                pd.Series(value_time, index=option_df.index, name=SliceColumn.EXCHANGE_TIME.value),
                                option_df['underlying_index'].rename(SliceColumn.UNDERLYING_INDEX.value),
                                option_df['underlying_price'].rename(SliceColumn.FORWARD_PRICE.value),
                                option_df['underlying_price'].rename(SliceColumn.SPOT_PRICE.value),
                                option_df['underlying_price'].rename(SliceColumn.USD_MULTIPLIER.value),
                                option_df['mark_price'].rename(SliceColumn.MARK_PRICE.value),
                                option_df['best_bid_price'].rename(SliceColumn.BID_PRICE.value),
                                option_df['best_ask_price'].rename(SliceColumn.ASK_PRICE.value),
                                option_df['best_bid_amount'].rename(SliceColumn.BID_SIZE.value),
                                option_df['best_ask_amount'].rename(SliceColumn.ASK_SIZE.value),
                                0.01 * option_df['mark_iv'].rename(SliceColumn.MARK_IV.value),
                                0.01 * option_df['bid_iv'].rename(SliceColumn.BID_IV.value),
                                0.01 * option_df['ask_iv'].rename(SliceColumn.ASK_IV.value),
                                greeks['delta'].rename(SliceColumn.DELTA.value),
                                greeks['vega'].rename(SliceColumn.VEGA.value),
                                greeks['theta'].rename(SliceColumn.THETA.value),
                                greeks['gamma'].rename(SliceColumn.GAMMA.value),
                                option_df['open_interest'].rename(SliceColumn.OPEN_INTEREST.value),
                                stats['volume'].rename(SliceColumn.VOLUME.value),
                                option_df['expiry_time'].apply(lambda x: x.strftime('%d%b%Y')).rename(SliceColumn.MATURITY_ID.value),
                                option_df['strike'].rename(SliceColumn.STRIKE.value),
                                option_df['option_type'].map({'call': 'C', 'put': 'P'}).rename(SliceColumn.OPTION_TYPE.value),
                                option_df['expiry_time'].rename(SliceColumn.EXPIRY.value),
                                option_df['ttm'].rename(SliceColumn.TTM.value),
                                pd.Series(0.0, index=option_df.index, name=SliceColumn.INTEREST_RATE.value)
                                ], axis=1)
    new_options_df[SliceColumn.CONTRACT_SIZE.value] = 0.1 if ticker == 'BTC' else 1.0
    new_options_df = new_options_df.reset_index(drop=True)
    # make sure all columns in SliceColumn exist
    new_options_df = new_options_df[[x.value for x in SliceColumn]]
    return new_options_df


def update_deribit_options_data(tickers: List[str] = ("ETH", "BTC"), is_print: bool = False) -> pd.Timestamp:
    """
    fetch live deribit data and append to database
    """
    current_time = pd.Timestamp.utcnow()  # this is ticker
    print(f"starting deribit update at {current_time}")
    for ticker in tickers:
        # timestamps[ticker] = current_time
        df = DeribitApi(ticker).fetch_live_data()
        file_path = get_deribit_local_file_path(current_time=current_time, ticker=ticker)
        # store raw df as file
        qis.save_df_to_csv(df=df, local_path=file_path)
        parsed = parse_deribit_options_data(ticker=ticker, df=df, value_time=current_time)
        # append pars to existing data
        file_path = get_deribit_appended_file_path(ticker=ticker)
        qis.append_df_to_feather(df=parsed, local_path=file_path, index_col=None)
        if is_print:
            print(f"Data saved for {ticker}")
    return current_time


class UnitTests(Enum):
    FILE_PATH = 1
    UPDATE_OPTIONS_DATA = 2
    LOAD_DERIBIT_OPTIONS_DF = 3


def run_unit_test(unit_test: UnitTests):

    pd.set_option('display.max_columns', 500)

    if unit_test == UnitTests.FILE_PATH:
        file_path = get_deribit_appended_file_path(ticker='BTC')
        print(file_path)

    elif unit_test == UnitTests.UPDATE_OPTIONS_DATA:
        timestamps = update_deribit_options_data()
        print(timestamps)

    elif unit_test == UnitTests.LOAD_DERIBIT_OPTIONS_DF:
        from option_chain_analytics.chain_ts import OptionsDataDFs
        from option_chain_analytics.chain_loader_from_ts import create_chain_from_from_options_dfs
        from option_chain_analytics.ts_loaders import load_local_deribit_contract_ts_data

        options_data_dfs = OptionsDataDFs(**load_local_deribit_contract_ts_data(ticker='ETH'))
        options_data_dfs.print()
        print(options_data_dfs.chain_ts.columns)
        time_index = options_data_dfs.get_timeindex()
        print(f"time_index={time_index}")

        value_time = pd.Timestamp('2023-10-27 06:20:03.160939+00:00')
        chain = create_chain_from_from_options_dfs(options_data_dfs=options_data_dfs, value_time=value_time)
        chain.print_slices_id()


if __name__ == '__main__':

    unit_test = UnitTests.LOAD_DERIBIT_OPTIONS_DF

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
