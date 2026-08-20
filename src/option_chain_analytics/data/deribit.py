"""Fetch public Deribit snapshots and load locally accumulated option history.

The network path queries Deribit's public instrument and order-book endpoints,
stores each raw snapshot as CSV, maps option rows into OCA's complete
``SliceColumn`` schema, and appends the normalized observations to one Feather
history per underlying. Network-only dependencies are imported lazily, so the
local history reader works without initializing a client or making a request.

Deribit option prices are inverse: BTC contracts are quoted in BTC and ETH
contracts in ETH. ``underlying_price`` is retained as both expiry forward and
USD multiplier, implied volatilities are converted from provider percentages to
decimals, and contract sizes remain 0.1 BTC or 1 ETH. The separate local spot
history is read from the configured Tardis/Deribit perpetual archive.

The module owns reusable software only. Raw responses and appended histories
remain private files below OCA's configured resource directory and are never
included in the distribution.
"""
from enum import Enum
from typing import Any, Dict, List, Literal, Union

import pandas as pd
import qis

# local paths
from option_chain_analytics import local_path as lp
from option_chain_analytics.conventions import TIME_FMT, compute_time_to_maturity

# internal
from option_chain_analytics.option_chain import SliceColumn

DERIBIT_LOCAL_PATH = f"{lp.get_resource_path()}deribit\\"


def get_deribit_local_file_path(current_time: pd.Timestamp,
                                ticker: Literal['BTC', 'ETH'] = 'ETH',
                                local_path: str = DERIBIT_LOCAL_PATH
                                ) -> str:
    """Construct the raw CSV path for one timestamped Deribit snapshot.

    Parameters
    ----------
    current_time : pandas.Timestamp
        Snapshot timestamp encoded with OCA's shared ``TIME_FMT`` convention.
    ticker : {'BTC', 'ETH'}, default 'ETH'
        Deribit currency whose snapshot is being stored.
    local_path : str, default DERIBIT_LOCAL_PATH
        Destination directory from OCA's centralized resource configuration.

    Returns
    -------
    str
        Full path ``<local_path>/<ticker>_<timestamp>.csv``.
    """
    file_path = f"{local_path}{ticker}_{current_time.strftime(TIME_FMT)}.csv"
    return file_path


def get_deribit_appended_file_path(ticker: Literal['BTC', 'ETH'] = 'ETH',
                                   local_path: str = DERIBIT_LOCAL_PATH
                                   ) -> str:
    """Construct the Feather path for an appended normalized Deribit history.

    Parameters
    ----------
    ticker : {'BTC', 'ETH'}, default 'ETH'
        Deribit currency stored in the history.
    local_path : str, default DERIBIT_LOCAL_PATH
        Directory containing normalized local histories.

    Returns
    -------
    str
        Full path ``<local_path>/<ticker>_appended_options.feather``.
    """
    file_path = f"{local_path}{ticker}_appended_options.feather"
    return file_path


@qis.timer
def load_local_deribit_contract_ts_data(ticker: Union[str, Literal['BTC', 'ETH']] = 'BTC',
                                        local_path: str = DERIBIT_LOCAL_PATH
                                        ) -> Dict[str, Any]:
    """Load appended Deribit options and their local perpetual price history.

    Parameters
    ----------
    ticker : {'BTC', 'ETH'}, default 'BTC'
        Deribit option currency to load.
    local_path : str, default DERIBIT_LOCAL_PATH
        Directory containing ``<ticker>_appended_options.feather``.

    Returns
    -------
    dict[str, Any]
        Stored option ``chain_ts``, corresponding perpetual ``spot_data``, and
        ``ticker`` suitable for ``OptionsDataDFs(**result)``.

    Notes
    -----
    Older appended histories may contain ``underlying_price`` without the
    canonical ``forward_price`` alias. The loader adds that alias without
    altering any provider observation.
    """
    from option_chain_analytics.data.tardis import TARDIS_FILES_LOCAL_PATH

    file_path = f"{local_path}{ticker}_appended_options.feather"
    chain_ts = qis.load_df_from_feather(local_path=file_path, index_col=None)
    if 'forward_price' not in chain_ts.columns:
        chain_ts['forward_price'] = chain_ts['underlying_price']

    spot_data = qis.load_df_from_feather(file_name=f"{ticker}_perp_data", local_path=TARDIS_FILES_LOCAL_PATH)
    return dict(chain_ts=chain_ts, spot_data=spot_data, ticker=ticker)


class DeribitApi:
    """Minimal client for Deribit's unauthenticated public option endpoints.

    Parameters
    ----------
    currency : {'BTC', 'ETH'}, default 'BTC'
        Currency supplied to the public instruments endpoint.

    Notes
    -----
    Each request is retried up to ten times because the bulk order-book loop can
    encounter transient public-endpoint failures. Authentication and trading
    endpoints are intentionally outside OCA's scope.
    """

    def __init__(self, currency: Literal['BTC', 'ETH'] = 'BTC'):
        """Initialize the public endpoint base URL and normalized currency."""
        self.url = 'https://www.deribit.com/api/v2/public/'
        self.currency = str.lower(currency)

    def get_live_instruments(self) -> pd.DataFrame:
        """Retrieve the current instrument catalogue for the configured currency.

        Returns
        -------
        pandas.DataFrame
            One row per live Deribit instrument with provider fields unchanged.

        Raises
        ------
        ValueError
            If no successful response is received after ten attempts.
        """
        import requests

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
            raise ValueError("could not get data after 10 attempts")
        return df

    def get_instruments_urls(self) -> List[str]:
        """Build one public order-book URL for every currently live instrument.

        Returns
        -------
        list[str]
            Fully qualified ``get_order_book`` URLs in catalogue order.
        """
        live_instruments = self.get_live_instruments()
        print(live_instruments)
        request_url = f"{self.url}get_order_book?instrument_name="
        url_storage = [f"{request_url}{instrument}" for instrument in live_instruments['instrument_name']]
        return url_storage

    def request_get(self, url) -> dict:
        """Request one public endpoint and return its ``result`` payload.

        Parameters
        ----------
        url : str
            Fully qualified Deribit public API URL.

        Returns
        -------
        dict or None
            Provider ``result`` payload, or ``None`` after ten failed attempts.
        """
        import requests

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
        """Collect order books and join them to the live instrument catalogue.

        Returns
        -------
        pandas.DataFrame
            Provider order-book fields joined with static instrument metadata,
            indexed by ``instrument_name``.
        """
        from tqdm import tqdm

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
    """Map one raw Deribit snapshot to the canonical option-observation schema.

    Parameters
    ----------
    df : pandas.DataFrame
        Joined live instrument and order-book response from
        :meth:`DeribitApi.fetch_live_data`.
    value_time : pandas.Timestamp
        Timestamp assigned to every observation in this atomic snapshot.
    ticker : str
        ``BTC`` or ``ETH``; determines the inverse contract size.

    Returns
    -------
    pandas.DataFrame
        Option rows containing every ``SliceColumn`` field in enum order.

    Notes
    -----
    Provider volatilities are percentages and are divided by 100. Expiry is
    converted from milliseconds to UTC, while prices remain in coin units and
    ``underlying_price`` supplies both forward and USD multiplier.
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
                                pd.Series(1.0, index=option_df.index, name=SliceColumn.DISCOUNT.value)
                                ], axis=1)
    new_options_df[SliceColumn.CONTRACT_SIZE.value] = 0.1 if ticker == 'BTC' else 1.0
    new_options_df = new_options_df.reset_index(drop=True)
    # make sure all columns in SliceColumn exist
    new_options_df = new_options_df[[x.value for x in SliceColumn]]
    return new_options_df


def update_deribit_options_data(tickers: List[str] = ("ETH", "BTC"), is_print: bool = False) -> pd.Timestamp:
    """Fetch, archive, normalize, and append live Deribit option snapshots.

    Parameters
    ----------
    tickers : sequence of str, default ('ETH', 'BTC')
        Deribit currencies updated at one shared snapshot timestamp.
    is_print : bool, default False
        Print a confirmation after each ticker is persisted.

    Returns
    -------
    pandas.Timestamp
        UTC timestamp assigned to all rows written by this update.

    Notes
    -----
    This function performs network and filesystem writes. It stores the complete
    raw response as CSV before appending normalized ``SliceColumn`` rows to the
    ticker's local Feather history.
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
    """Runnable local Deribit data cases."""

    FILE_PATH = 1
    UPDATE_OPTIONS_DATA = 2
    LOAD_DERIBIT_OPTIONS_DF = 3


def run_unit_test(unit_test: UnitTests):
    """Run the selected local Deribit fetch or loading diagnostic."""

    pd.set_option('display.max_columns', 500)

    if unit_test == UnitTests.FILE_PATH:
        file_path = get_deribit_appended_file_path(ticker='BTC')
        print(file_path)

    elif unit_test == UnitTests.UPDATE_OPTIONS_DATA:
        timestamps = update_deribit_options_data()
        print(timestamps)

    elif unit_test == UnitTests.LOAD_DERIBIT_OPTIONS_DF:
        from option_chain_analytics.data.deribit import load_local_deribit_contract_ts_data
        from option_chain_analytics.option_data import OptionsDataDFs
        from option_chain_analytics.reconstruction import create_chain_at_time

        options_data_dfs = OptionsDataDFs(**load_local_deribit_contract_ts_data(ticker='ETH'))
        options_data_dfs.print()
        print(options_data_dfs.chain_ts.columns)
        time_index = options_data_dfs.get_timeindex()
        print(f"time_index={time_index}")

        value_time = pd.Timestamp('2023-10-27 06:20:03.160939+00:00')
        chain = create_chain_at_time(options_data=options_data_dfs, value_time=value_time)
        chain.print_slices_id()


if __name__ == '__main__':

    unit_test = UnitTests.LOAD_DERIBIT_OPTIONS_DF

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
