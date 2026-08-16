"""
add proprietary data loaders here
the return type is Dict[str, Union[Dict[str, pd.DataFrame], pd.DataFrame]]: where str is SliceColumn

different sources are integrated using wrapper:
ts_data_loader_wrapper()
"""

from enum import Enum
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Union

import numpy as np
import pandas as pd
import qis

# public data api
from option_chain_analytics import local_path as lp
from option_chain_analytics.option_chain import SliceColumn

DERIBIT_LOCAL_PATH = f"{lp.get_resource_path()}\\deribit\\"
TARDIS_FILES_LOCAL_PATH = f"{lp.get_resource_path()}tardis\\"
VLAD_FILES_LOCAL_PATH = f"{lp.get_resource_path()}vlad_vols\\"

VLAD_SOURCE_COLUMNS = (
    'exdate',
    'strike_price',
    'cp_flag',
    'mid_price',
    'bid_size',
    'best_bid',
    'offer_size',
    'best_offer',
    'open_interest',
    'date',
    'impl_df',
    'impl_fw',
    'mid_vols',
    'dte',
    'vega',
    'delta',
)


class DataSource(Enum):
    TARDIS_LOCAL = 1
    DERIBIT_LOCAL = 2
    VLAD_LOCAL = 3


def ts_data_loader_wrapper(data_source: DataSource = DataSource.TARDIS_LOCAL,
                           ticker: str = 'BTC',
                           **kwargs
                           ) -> Dict[str, Any]:
    """
    generic wrapper for loading
    """
    if data_source == DataSource.TARDIS_LOCAL:
        return load_local_tardis_contract_ts_data(ticker=ticker, **kwargs)

    elif data_source == DataSource.DERIBIT_LOCAL:
        return load_local_deribit_contract_ts_data(ticker=ticker, **kwargs)

    elif data_source == DataSource.VLAD_LOCAL:
        return load_local_vlad_options_data(ticker=ticker, **kwargs)

    else:
        raise NotImplementedError(f"{data_source}")


@qis.timer
def load_local_tardis_contract_ts_data(ticker: str = 'BTC',
                                       local_path: str = TARDIS_FILES_LOCAL_PATH
                                       ) -> Dict[str, Any]:
    """
    this loader is using prop data in feather
    """
    chain_ts = qis.load_df_from_feather(file_name=f"{ticker}_freq_H",
                                        index_col=None,
                                        local_path=local_path)
    if 'forward_price' not in chain_ts.columns:  # for consistency with old anlytics
        chain_ts['forward_price'] = chain_ts['underlying_price']

    spot_data = qis.load_df_from_feather(file_name=f"{ticker}_perp_freq_H",
                                         index_col='timestamp',
                                         local_path=local_path)
    return dict(chain_ts=chain_ts, spot_data=spot_data, ticker=ticker)


@qis.timer
def load_local_deribit_contract_ts_data(ticker: Union[str, Literal['BTC', 'ETH']] = 'BTC',
                                        local_path: str = DERIBIT_LOCAL_PATH
                                        ) -> Dict[str, Any]:
    """
    this loader is using deribit public data in feather
    """
    file_path = f"{local_path}{ticker}_appended_options.feather"  # same as in get_deribit_appended_file_path
    chain_ts = qis.load_df_from_feather(local_path=file_path, index_col=None)
    if 'forward_price' not in chain_ts.columns:
        chain_ts['forward_price'] = chain_ts['underlying_price']

    spot_data = qis.load_df_from_feather(file_name=f"{ticker}_perp_data", local_path=TARDIS_FILES_LOCAL_PATH)
    return dict(chain_ts=chain_ts, spot_data=spot_data, ticker=ticker)


def _to_new_york_naive(timestamp: Optional[pd.Timestamp], is_end: bool = False) -> Optional[pd.Timestamp]:
    if timestamp is None:
        return None
    timestamp = pd.Timestamp(timestamp)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert('America/New_York').tz_localize(None)
    if is_end and timestamp == timestamp.normalize():
        timestamp = timestamp + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return timestamp


def _load_vlad_source_frame(file_path: Path,
                            start: Optional[pd.Timestamp] = None,
                            end: Optional[pd.Timestamp] = None
                            ) -> pd.DataFrame:
    start = _to_new_york_naive(start)
    end = _to_new_york_naive(end, is_end=True)
    if start is None and end is None:
        return pd.read_feather(file_path, columns=list(VLAD_SOURCE_COLUMNS))

    import pyarrow as pa
    import pyarrow.ipc as ipc

    reader = ipc.RecordBatchFileReader(pa.memory_map(str(file_path), 'r'))
    missing = set(VLAD_SOURCE_COLUMNS).difference(reader.schema.names)
    if missing:
        raise ValueError(f"missing vlad_vols columns: {sorted(missing)}")
    column_indices = [reader.schema.get_field_index(column) for column in VLAD_SOURCE_COLUMNS]
    frames = []
    for batch_idx in range(reader.num_record_batches):
        frame = reader.get_batch(batch_idx).select(column_indices).to_pandas()
        if start is not None:
            frame = frame.loc[frame['date'] >= start]
        if end is not None:
            frame = frame.loc[frame['date'] <= end]
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=VLAD_SOURCE_COLUMNS)
    return pd.concat(frames, axis=0, ignore_index=True)


def _to_utc_from_new_york(values: pd.Series) -> pd.Series:
    values = pd.to_datetime(values)
    if values.dt.tz is None:
        values = values.dt.tz_localize('America/New_York')
    else:
        values = values.dt.tz_convert('America/New_York')
    return values.dt.tz_convert('UTC')


def _prepare_spot_data(chain_ts: pd.DataFrame,
                       spot_data: Optional[Union[pd.Series, pd.DataFrame]],
                       is_use_front_forward_as_spot: bool
                       ) -> pd.DataFrame:
    exchange_time = SliceColumn.EXCHANGE_TIME.value
    forward_price = SliceColumn.FORWARD_PRICE.value
    ttm = SliceColumn.TTM.value
    time_index = pd.DatetimeIndex(chain_ts[exchange_time].drop_duplicates().sort_values())

    if spot_data is not None:
        if isinstance(spot_data, pd.Series):
            spot_data = spot_data.rename('close').to_frame()
        else:
            spot_data = spot_data.copy()
        if 'close' not in spot_data.columns:
            raise ValueError("spot_data must contain a 'close' column")
        spot_index = pd.DatetimeIndex(pd.to_datetime(spot_data.index))
        if spot_index.tz is None:
            spot_index = spot_index.tz_localize('America/New_York')
        spot_data.index = spot_index.tz_convert('UTC')
        spot_data = spot_data.sort_index().reindex(time_index, method='ffill')
        spot_data.attrs['spot_source'] = 'supplied'
        return spot_data

    if is_use_front_forward_as_spot:
        front = chain_ts.loc[chain_ts[ttm] >= 0.0, [exchange_time, ttm, forward_price]]
        front = front.sort_values([exchange_time, ttm]).drop_duplicates(exchange_time)
        spot_data = front.set_index(exchange_time)[forward_price].rename('close').to_frame()
        spot_data = spot_data.reindex(time_index)
        spot_data.attrs['spot_source'] = 'front_forward_proxy'
        return spot_data

    spot_data = pd.DataFrame({'close': np.nan}, index=time_index)
    spot_data.attrs['spot_source'] = 'missing'
    return spot_data


def _compute_vlad_bid_ask_iv(chain_ts: pd.DataFrame) -> None:
    import vanilla_option_pricers as bsm

    bid_iv = np.full(len(chain_ts.index), np.nan)
    ask_iv = np.full(len(chain_ts.index), np.nan)
    grouped = chain_ts.groupby(
        [SliceColumn.EXCHANGE_TIME.value, SliceColumn.MATURITY_ID.value],
        observed=True,
        sort=False,
    )
    for positions in grouped.indices.values():
        frame = chain_ts.iloc[positions]
        ttm = float(frame[SliceColumn.TTM.value].iloc[0])
        forward = float(frame[SliceColumn.FORWARD_PRICE.value].iloc[0])
        discount = float(frame[SliceColumn.DISCOUNT.value].iloc[0])
        if ttm <= 0.0 or forward <= 0.0 or discount <= 0.0:
            continue
        strikes = frame[SliceColumn.STRIKE.value].to_numpy(float)
        option_types = frame[SliceColumn.OPTION_TYPE.value].to_numpy(str)
        for result, price_column in (
            (bid_iv, SliceColumn.BID_PRICE.value),
            (ask_iv, SliceColumn.ASK_PRICE.value),
        ):
            prices = frame[price_column].to_numpy(float)
            for position, strike, option_type, price in zip(positions, strikes, option_types, prices):
                result[position] = bsm.infer_bsm_implied_vol(
                    ttm=ttm,
                    forward=forward,
                    strike=strike,
                    optiontype=str(option_type),
                    given_price=price,
                    discfactor=discount,
                )
    chain_ts[SliceColumn.BID_IV.value] = bid_iv
    chain_ts[SliceColumn.ASK_IV.value] = ask_iv


def map_vlad_options_data(source: pd.DataFrame,
                          ticker: Union[str, Literal['SPX', 'VIX']] = 'SPX',
                          spot_data: Optional[Union[pd.Series, pd.DataFrame]] = None,
                          is_use_front_forward_as_spot: bool = False,
                          is_compute_bid_ask_iv: bool = False
                          ) -> Dict[str, Any]:
    """Map a vlad_vols SPX/VIX table to the ``OptionsDataDFs`` constructor format.

    Source observations are treated as 16:00 New York time and expiries as
    16:15 New York time, matching the source ``dte`` convention. The source
    has no spot series or bid/ask implied volatilities. Those fields remain
    missing unless the corresponding explicit option is supplied.
    """
    ticker = ticker.upper()
    if ticker not in ('SPX', 'VIX'):
        raise ValueError(f"unsupported vlad_vols ticker={ticker}")
    missing = set(VLAD_SOURCE_COLUMNS).difference(source.columns)
    if missing:
        raise ValueError(f"missing vlad_vols columns: {sorted(missing)}")

    source = source.loc[:, list(VLAD_SOURCE_COLUMNS)].copy()
    exchange_time = _to_utc_from_new_york(source['date'])
    expiry_local = pd.to_datetime(source['exdate']).dt.normalize() + pd.Timedelta(hours=16, minutes=15)
    expiry = _to_utc_from_new_york(expiry_local)
    strike = pd.to_numeric(source['strike_price'])
    option_type = source['cp_flag'].astype('string').str.upper()
    if option_type.isna().any() or not option_type.isin(('C', 'P')).all():
        raise ValueError(f"unsupported option types: {sorted(option_type.dropna().unique())}")
    maturity_id = expiry.dt.strftime('%d%b%Y')
    strike_id = strike.astype('string')
    contract = ticker + '-' + expiry.dt.strftime('%Y%m%d') + '-' + option_type + '-' + strike_id

    chain_ts = pd.DataFrame(
        {
            SliceColumn.CONTRACT.value: contract,
            SliceColumn.EXCHANGE_TIME.value: exchange_time,
            SliceColumn.UNDERLYING_INDEX.value: ticker,
            SliceColumn.FORWARD_PRICE.value: pd.to_numeric(source['impl_fw']),
            SliceColumn.SPOT_PRICE.value: np.nan,
            SliceColumn.USD_MULTIPLIER.value: 1.0,
            SliceColumn.MARK_PRICE.value: pd.to_numeric(source['mid_price']),
            SliceColumn.BID_PRICE.value: pd.to_numeric(source['best_bid']),
            SliceColumn.ASK_PRICE.value: pd.to_numeric(source['best_offer']),
            SliceColumn.BID_SIZE.value: pd.to_numeric(source['bid_size']),
            SliceColumn.ASK_SIZE.value: pd.to_numeric(source['offer_size']),
            SliceColumn.MARK_IV.value: pd.to_numeric(source['mid_vols']),
            SliceColumn.BID_IV.value: np.nan,
            SliceColumn.ASK_IV.value: np.nan,
            SliceColumn.DELTA.value: pd.to_numeric(source['delta']),
            SliceColumn.VEGA.value: pd.to_numeric(source['vega']),
            SliceColumn.THETA.value: np.nan,
            SliceColumn.GAMMA.value: np.nan,
            SliceColumn.OPEN_INTEREST.value: pd.to_numeric(source['open_interest']),
            SliceColumn.VOLUME.value: np.nan,
            SliceColumn.MATURITY_ID.value: maturity_id,
            SliceColumn.STRIKE.value: strike,
            SliceColumn.OPTION_TYPE.value: option_type,
            SliceColumn.EXPIRY.value: expiry,
            SliceColumn.TTM.value: pd.to_numeric(source['dte']),
            SliceColumn.CONTRACT_SIZE.value: 100.0,
            SliceColumn.DISCOUNT.value: pd.to_numeric(source['impl_df']),
        }
    )
    chain_ts = chain_ts.drop_duplicates(
        subset=[SliceColumn.EXCHANGE_TIME.value, SliceColumn.CONTRACT.value],
        keep='last',
    ).reset_index(drop=True)
    spot_data = _prepare_spot_data(
        chain_ts=chain_ts,
        spot_data=spot_data,
        is_use_front_forward_as_spot=is_use_front_forward_as_spot,
    )
    chain_ts[SliceColumn.SPOT_PRICE.value] = chain_ts[SliceColumn.EXCHANGE_TIME.value].map(spot_data['close'])
    if is_compute_bid_ask_iv:
        _compute_vlad_bid_ask_iv(chain_ts)
    chain_ts = chain_ts[[column.value for column in SliceColumn]]
    chain_ts.attrs['source'] = 'vlad_vols'
    chain_ts.attrs['spot_source'] = spot_data.attrs['spot_source']
    return dict(chain_ts=chain_ts, spot_data=spot_data, ticker=ticker)


@qis.timer
def load_local_vlad_options_data(ticker: Union[str, Literal['SPX', 'VIX']] = 'SPX',
                                 local_path: str = VLAD_FILES_LOCAL_PATH,
                                 start: Optional[pd.Timestamp] = None,
                                 end: Optional[pd.Timestamp] = None,
                                 spot_data: Optional[Union[pd.Series, pd.DataFrame]] = None,
                                 is_use_front_forward_as_spot: bool = False,
                                 is_compute_bid_ask_iv: bool = False
                                 ) -> Dict[str, Any]:
    """Load local SPX/VIX vlad_vols data in ``OptionsDataDFs`` format."""
    ticker = ticker.upper()
    file_names = {'SPX': 'spx_options.feather', 'VIX': 'vix_options.feather'}
    if ticker not in file_names:
        raise ValueError(f"unsupported vlad_vols ticker={ticker}")
    source = _load_vlad_source_frame(
        file_path=Path(local_path).joinpath(file_names[ticker]),
        start=start,
        end=end,
    )
    return map_vlad_options_data(
        source=source,
        ticker=ticker,
        spot_data=spot_data,
        is_use_front_forward_as_spot=is_use_front_forward_as_spot,
        is_compute_bid_ask_iv=is_compute_bid_ask_iv,
    )


class UnitTests(Enum):
    LOAD_TARDIS_OPTIONS_DF = 1
    LOAD_DERIBIT_OPTIONS_DF = 2


def run_unit_test(unit_test: UnitTests):

    from option_chain_analytics.chain_ts import OptionsDataDFs

    pd.set_option('display.max_columns', 500)

    if unit_test == UnitTests.LOAD_TARDIS_OPTIONS_DF:
        options_data_dfs = OptionsDataDFs(**load_local_tardis_contract_ts_data(ticker='ETH'))
        options_data_dfs.print()

    elif unit_test == UnitTests.LOAD_DERIBIT_OPTIONS_DF:
        options_data_dfs = OptionsDataDFs(**load_local_deribit_contract_ts_data(ticker='ETH'))
        options_data_dfs.print()


if __name__ == '__main__':

    unit_test = UnitTests.LOAD_TARDIS_OPTIONS_DF

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
