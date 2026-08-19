"""Normalize local/provider option histories into OCA time-series containers.

The module exposes a common loader dispatcher plus source-specific adapters for
Tardis, Deribit, CBOE, and optional ThetaData inputs. Local source and cache
directories derive from :mod:`option_chain_analytics.local_path`; normalized
adapters return ``chain_ts``, aligned ``spot_data``, and ``ticker`` suitable for
``OptionsDataDFs(**result)``.
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

DERIBIT_LOCAL_PATH = f"{lp.get_resource_path()}deribit\\"
TARDIS_FILES_LOCAL_PATH = f"{lp.get_resource_path()}tardis\\"
CBOE_FILES_LOCAL_PATH = f"{lp.get_resource_path()}cboe_options\\"

NORMALIZED_OPTIONS_CACHE_FORMAT = 'option_chain_analytics.options.normalized'
NORMALIZED_OPTIONS_CACHE_SCHEMA_VERSION = '3'
NORMALIZED_OPTIONS_DTYPE_POLICY = 'slice_column_string_timestamp_utc_float64_v1'

CBOE_CACHE_FORMAT = NORMALIZED_OPTIONS_CACHE_FORMAT
CBOE_CACHE_SCHEMA_VERSION = NORMALIZED_OPTIONS_CACHE_SCHEMA_VERSION
CBOE_ANALYTICS_POLICY = 'parity_huber_vip_bsm'
CBOE_SOURCE_FILE_NAMES = {'SPX': 'spx_options.feather', 'VIX': 'vix_options.feather'}
CBOE_CACHE_FILE_NAMES = {'SPX': 'spx_options_oca.parquet', 'VIX': 'vix_options_oca.parquet'}
CBOE_PRODUCT_POLICIES = {
    'SPX': {
        'settlement_policy': 'spxw_pm_1600_new_york',
        'expiry_hour': 16,
        'expiry_minute': 0,
    },
    'VIX': {
        'settlement_policy': 'vix_soq_am_0930_new_york',
        'expiry_hour': 9,
        'expiry_minute': 30,
    },
}
TARDIS_EOD_CACHE_FORMAT = NORMALIZED_OPTIONS_CACHE_FORMAT
TARDIS_EOD_CACHE_SCHEMA_VERSION = NORMALIZED_OPTIONS_CACHE_SCHEMA_VERSION
TARDIS_EOD_ANALYTICS_POLICY = 'provider_iv_greeks_discount_one'
TARDIS_EOD_SPOT_POLICY = 'exact_perpetual_index_then_option_index'
TARDIS_EOD_SOURCE_FILE_NAMES = {'BTC': 'BTC_freq_H.feather', 'ETH': 'ETH_freq_H.feather'}
TARDIS_EOD_SPOT_FILE_NAMES = {'BTC': 'BTC_perp_freq_H.feather', 'ETH': 'ETH_perp_freq_H.feather'}
TARDIS_EOD_CACHE_FILE_NAMES = {'BTC': 'btc_options_oca.parquet', 'ETH': 'eth_options_oca.parquet'}
TARDIS_EOD_HOUR_UTC = 8
SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0

OCA_STRING_COLUMNS = (
    SliceColumn.CONTRACT.value,
    SliceColumn.UNDERLYING_INDEX.value,
    SliceColumn.MATURITY_ID.value,
    SliceColumn.OPTION_TYPE.value,
)
OCA_TIMESTAMP_COLUMNS = (
    SliceColumn.EXCHANGE_TIME.value,
    SliceColumn.EXPIRY.value,
)
OCA_NUMERIC_COLUMNS = tuple(
    column.value
    for column in SliceColumn
    if column.value not in OCA_STRING_COLUMNS and column.value not in OCA_TIMESTAMP_COLUMNS
)

CBOE_SOURCE_COLUMNS = (
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
TARDIS_EOD_SOURCE_COLUMNS = (
    'contract',
    'exchange_time',
    'underlying_index',
    'underlying_price',
    'usd_multiplier',
    'mark_price',
    'bid_price',
    'ask_price',
    'bid_size',
    'ask_size',
    'mark_iv',
    'bid_iv',
    'ask_iv',
    'delta',
    'vega',
    'theta',
    'gamma',
    'open_interest',
    'volume',
    'mat_id',
    'strike',
    'optiontype',
    'expiry',
    'ttm',
    'contract_size',
    'interest_rate',
)


def _coerce_oca_options_frame(chain_ts: pd.DataFrame) -> pd.DataFrame:
    """Return one canonical pandas representation of the ``SliceColumn`` schema."""
    columns = [column.value for column in SliceColumn]
    missing = set(columns).difference(chain_ts.columns)
    if missing:
        raise ValueError(f"missing OCA option columns: {sorted(missing)}")

    chain_ts = chain_ts.loc[:, columns].copy()
    for column in OCA_STRING_COLUMNS:
        chain_ts[column] = chain_ts[column].astype('string')
    for column in OCA_TIMESTAMP_COLUMNS:
        chain_ts[column] = pd.to_datetime(chain_ts[column], utc=True)
    for column in OCA_NUMERIC_COLUMNS:
        chain_ts[column] = pd.to_numeric(chain_ts[column], errors='coerce').astype('float64')
    return chain_ts


def _get_oca_options_arrow_schema() -> Any:
    """Return the provider-neutral physical Parquet schema for option observations."""
    import pyarrow as pa

    fields = []
    for column in SliceColumn:
        if column.value in OCA_STRING_COLUMNS:
            dtype = pa.string()
        elif column.value in OCA_TIMESTAMP_COLUMNS:
            dtype = pa.timestamp('ns', tz='UTC')
        else:
            dtype = pa.float64()
        fields.append(pa.field(column.value, dtype))
    return pa.schema(fields)


def _to_oca_options_arrow_table(chain_ts: pd.DataFrame, metadata: Dict[bytes, bytes]) -> Any:
    """Convert a canonical option panel to an Arrow table with OCA metadata."""
    import pyarrow as pa

    table = pa.Table.from_pandas(
        _coerce_oca_options_frame(chain_ts),
        schema=_get_oca_options_arrow_schema(),
        preserve_index=False,
        safe=True,
    )
    return table.replace_schema_metadata({**(table.schema.metadata or {}), **metadata})


class DataSource(Enum):
    """Supported local and optional-provider time-series adapters."""

    TARDIS_LOCAL = 1
    DERIBIT_LOCAL = 2
    CBOE_LOCAL = 3
    THETADATA_EOD = 4
    TARDIS_EOD_LOCAL = 5


def ts_data_loader_wrapper(data_source: DataSource = DataSource.TARDIS_LOCAL,
                           ticker: str = 'BTC',
                           **kwargs
                           ) -> Dict[str, Any]:
    """Load one provider source into the ``OptionsDataDFs`` constructor schema."""
    if data_source == DataSource.TARDIS_LOCAL:
        return load_local_tardis_contract_ts_data(ticker=ticker, **kwargs)

    elif data_source == DataSource.DERIBIT_LOCAL:
        return load_local_deribit_contract_ts_data(ticker=ticker, **kwargs)

    elif data_source == DataSource.CBOE_LOCAL:
        return load_local_cboe_options_data(ticker=ticker, **kwargs)

    elif data_source == DataSource.THETADATA_EOD:
        from option_chain_analytics.data.thetadata import load_thetadata_eod_options_data

        return load_thetadata_eod_options_data(ticker=ticker, **kwargs)

    elif data_source == DataSource.TARDIS_EOD_LOCAL:
        return load_local_tardis_eod_options_data(ticker=ticker, **kwargs)

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
    """Convert a filter boundary to timezone-naive New York source time."""
    if timestamp is None:
        return None
    timestamp = pd.Timestamp(timestamp)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert('America/New_York').tz_localize(None)
    if is_end and timestamp == timestamp.normalize():
        timestamp = timestamp + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return timestamp


def _load_cboe_source_frame(file_path: Path,
                            start: Optional[pd.Timestamp] = None,
                            end: Optional[pd.Timestamp] = None
                            ) -> pd.DataFrame:
    """Read selected CBOE source rows without loading unrelated record batches."""
    start = _to_new_york_naive(start)
    end = _to_new_york_naive(end, is_end=True)
    if start is None and end is None:
        return pd.read_feather(file_path, columns=list(CBOE_SOURCE_COLUMNS))

    import pyarrow as pa
    import pyarrow.ipc as ipc

    reader = ipc.RecordBatchFileReader(pa.memory_map(str(file_path), 'r'))
    missing = set(CBOE_SOURCE_COLUMNS).difference(reader.schema.names)
    if missing:
        raise ValueError(f"missing CBOE option columns: {sorted(missing)}")
    column_indices = [reader.schema.get_field_index(column) for column in CBOE_SOURCE_COLUMNS]
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
        return pd.DataFrame(columns=CBOE_SOURCE_COLUMNS)
    return pd.concat(frames, axis=0, ignore_index=True)


def _cboe_file_path(ticker: str, local_path: str, file_names: Dict[str, str]) -> Path:
    """Resolve one supported CBOE ticker to its source or cache file path."""
    ticker = ticker.upper()
    if ticker not in file_names:
        raise ValueError(f"unsupported CBOE option ticker={ticker}")
    return Path(local_path).joinpath(file_names[ticker])


def _cboe_cache_metadata(ticker: str, source_path: Path) -> Dict[bytes, bytes]:
    """Build cache metadata including schema, policy, and source fingerprint."""
    source_stat = source_path.stat()
    policy = _get_cboe_product_policy(ticker=ticker)
    values = {
        'oca_cache_format': CBOE_CACHE_FORMAT,
        'oca_cache_schema_version': CBOE_CACHE_SCHEMA_VERSION,
        'oca_dtype_policy': NORMALIZED_OPTIONS_DTYPE_POLICY,
        'oca_ticker': ticker,
        'oca_provider': 'cboe',
        'oca_frequency': 'eod',
        'oca_observation_policy': 'exact_1600_new_york',
        'oca_price_convention': 'usd_per_contract',
        'oca_settlement_policy': policy['settlement_policy'],
        'oca_analytics': CBOE_ANALYTICS_POLICY,
        'oca_source_file': source_path.name,
        'oca_source_size': str(source_stat.st_size),
        'oca_source_mtime_ns': str(source_stat.st_mtime_ns),
        'oca_created_utc': pd.Timestamp.now(tz='UTC').isoformat(),
    }
    return {key.encode(): value.encode() for key, value in values.items()}


def _read_cboe_cache_metadata(cache_path: Path) -> Dict[str, str]:
    """Read decoded OCA metadata from a normalized Parquet cache."""
    import pyarrow.parquet as pq

    raw_metadata = pq.ParquetFile(cache_path).metadata.metadata or {}
    return {key.decode(): value.decode() for key, value in raw_metadata.items() if key.startswith(b'oca_')}


def _validate_cboe_cache(cache_path: Path, ticker: str, source_path: Path) -> None:
    """Reject a CBOE cache whose policy, schema, or fingerprint is stale."""
    metadata = _read_cboe_cache_metadata(cache_path=cache_path)
    policy = _get_cboe_product_policy(ticker=ticker)
    expected = {
        'oca_cache_format': CBOE_CACHE_FORMAT,
        'oca_cache_schema_version': CBOE_CACHE_SCHEMA_VERSION,
        'oca_dtype_policy': NORMALIZED_OPTIONS_DTYPE_POLICY,
        'oca_ticker': ticker,
        'oca_provider': 'cboe',
        'oca_frequency': 'eod',
        'oca_observation_policy': 'exact_1600_new_york',
        'oca_price_convention': 'usd_per_contract',
        'oca_settlement_policy': policy['settlement_policy'],
        'oca_analytics': CBOE_ANALYTICS_POLICY,
    }
    mismatches = {
        key: (metadata.get(key), value)
        for key, value in expected.items()
        if metadata.get(key) != value
    }
    if source_path.exists():
        source_stat = source_path.stat()
        source_expected = {
            'oca_source_file': source_path.name,
            'oca_source_size': str(source_stat.st_size),
            'oca_source_mtime_ns': str(source_stat.st_mtime_ns),
        }
        mismatches.update(
            {
                key: (metadata.get(key), value)
                for key, value in source_expected.items()
                if metadata.get(key) != value
            }
        )
    if mismatches:
        details = ', '.join(
            f"{key}={actual!r} (expected {expected_value!r})"
            for key, (actual, expected_value) in mismatches.items()
        )
        raise ValueError(
            f"incompatible or stale CBOE cache {cache_path}: {details}. "
            "Rebuild it with build_local_cboe_options_cache(..., overwrite=True), "
            "or pass is_use_cache=False."
        )


def _to_cboe_cache_utc(timestamp: Optional[pd.Timestamp], is_end: bool = False) -> Optional[pd.Timestamp]:
    """Convert a CBOE date/filter boundary from New York time to UTC."""
    timestamp = _to_new_york_naive(timestamp=timestamp, is_end=is_end)
    if timestamp is None:
        return None
    return timestamp.tz_localize('America/New_York').tz_convert('UTC')


def _load_cboe_cache_frame(cache_path: Path,
                           ticker: str,
                           source_path: Path,
                           start: Optional[pd.Timestamp] = None,
                           end: Optional[pd.Timestamp] = None
                           ) -> pd.DataFrame:
    """Validate and read a date-filtered normalized CBOE cache frame."""
    _validate_cboe_cache(cache_path=cache_path, ticker=ticker, source_path=source_path)
    filters = []
    exchange_time = SliceColumn.EXCHANGE_TIME.value
    start_utc = _to_cboe_cache_utc(timestamp=start)
    end_utc = _to_cboe_cache_utc(timestamp=end, is_end=True)
    if start_utc is not None:
        filters.append((exchange_time, '>=', start_utc))
    if end_utc is not None:
        filters.append((exchange_time, '<=', end_utc))
    chain_ts = pd.read_parquet(
        cache_path,
        columns=[column.value for column in SliceColumn],
        filters=filters or None,
    )
    return _coerce_oca_options_frame(chain_ts.reset_index(drop=True))


def _to_utc_from_new_york(values: pd.Series) -> pd.Series:
    """Normalize New York local timestamps to timezone-aware UTC values."""
    values = pd.to_datetime(values)
    if values.dt.tz is None:
        values = values.dt.tz_localize('America/New_York')
    else:
        values = values.dt.tz_convert('America/New_York')
    return values.dt.tz_convert('UTC')


def _get_cboe_product_policy(ticker: str) -> Dict[str, Any]:
    """Return settlement and expiry-time policy for a supported CBOE product."""
    ticker = ticker.upper()
    if ticker not in CBOE_PRODUCT_POLICIES:
        raise ValueError(f"unsupported CBOE option ticker={ticker}")
    return CBOE_PRODUCT_POLICIES[ticker]


def _get_cboe_expiry_local(source: pd.DataFrame, ticker: str) -> pd.Series:
    """Construct product-specific expiry timestamps in New York local time."""
    policy = _get_cboe_product_policy(ticker=ticker)
    return pd.to_datetime(source['exdate']).dt.normalize() + pd.Timedelta(
        hours=policy['expiry_hour'],
        minutes=policy['expiry_minute'],
    )


def _compute_cboe_ttm(source: pd.DataFrame, ticker: str) -> pd.Series:
    """Compute year-fraction maturity using the product's settlement time."""
    expiry_local = _get_cboe_expiry_local(source=source, ticker=ticker)
    observation_local = pd.to_datetime(source['date'])
    return (expiry_local - observation_local).dt.total_seconds() / SECONDS_PER_YEAR


def _infer_cboe_slice_forward_discount(frame: pd.DataFrame) -> Optional[tuple[float, float]]:
    """Infer one expiry slice's forward and discount from paired bid/ask quotes."""
    from option_chain_analytics.fitters.forward_discount import imply_forward_discount_from_bid_ask_prices

    quote_columns = ['best_bid', 'best_offer']
    calls = (
        frame.loc[frame['cp_flag'].eq('C')]
        .drop_duplicates('strike_price', keep='last')
        .set_index('strike_price')[quote_columns]
    )
    puts = (
        frame.loc[frame['cp_flag'].eq('P')]
        .drop_duplicates('strike_price', keep='last')
        .set_index('strike_price')[quote_columns]
    )
    if calls.empty or puts.empty:
        return None
    return imply_forward_discount_from_bid_ask_prices(
        calls_bid_ask=calls,
        put_bid_ask=puts,
        discfactor_lower_bound=0.5,
        discfactor_upper_bound=1.5,
        niters=8,
    )


def _infer_cboe_mark_vols(
    frame: pd.DataFrame,
    *,
    forward: float,
    discount: float,
    ttm: float,
) -> np.ndarray:
    """Infer mark implied volatilities for one reconstructed CBOE slice."""
    import vanilla_option_pricers as bsm
    from numba.typed import List

    vols = np.full(len(frame.index), np.nan)
    if ttm <= 0.0:
        return vols
    strikes = frame['strike_price'].to_numpy(float)
    prices = frame['mid_price'].to_numpy(float)
    option_types = List(frame['cp_flag'].astype(str).tolist())
    try:
        return np.asarray(
            bsm.infer_bsm_ivols_from_slice_prices(
                ttm=ttm,
                forward=forward,
                discfactor=discount,
                strikes=strikes,
                optiontypes=option_types,
                model_prices=prices,
            ),
            dtype=float,
        )
    except (ValueError, ZeroDivisionError):
        for idx, (strike, option_type, price) in enumerate(zip(strikes, option_types, prices)):
            try:
                vols[idx] = bsm.infer_bsm_implied_vol(
                    ttm=ttm,
                    forward=forward,
                    strike=strike,
                    optiontype=str(option_type),
                    given_price=price,
                    discfactor=discount,
                )
            except (ValueError, ZeroDivisionError):
                continue
        return vols


def _compute_cboe_mark_delta_vega(
    frame: pd.DataFrame,
    *,
    forward: float,
    discount: float,
    ttm: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute forward delta and present-value vega for valid CBOE quotes."""
    import vanilla_option_pricers as bsm
    from numba.typed import List

    deltas = np.full(len(frame.index), np.nan)
    vegas = np.full(len(frame.index), np.nan)
    if ttm <= 0.0:
        return deltas, vegas
    strikes = frame['strike_price'].to_numpy(float)
    vols = frame['mid_vols'].to_numpy(float)
    valid = np.isfinite(strikes) & np.isfinite(vols) & (strikes > 0.0) & (vols > 0.0)
    if not np.any(valid):
        return deltas, vegas
    option_types = List(frame.loc[valid, 'cp_flag'].astype(str).tolist())
    deltas[valid] = discount * bsm.compute_bsm_vanilla_slice_deltas(
        ttm=ttm,
        forward=forward,
        strikes=strikes[valid],
        vols=vols[valid],
        optiontypes=option_types,
    )
    vegas[valid] = discount * bsm.compute_bsm_slice_vegas(
        ttm=ttm,
        forward=forward,
        strikes=strikes[valid],
        vols=vols[valid],
        optiontypes=option_types,
    )
    return deltas, vegas


def reconstruct_cboe_source_analytics(
    source: pd.DataFrame,
    ticker: Union[str, Literal['SPX', 'VIX']] = 'SPX',
) -> pd.DataFrame:
    """Reconstruct provider-specific CBOE analytics from bid/ask quote slices.

    The quote midpoint replaces legacy QP marks. Forward and discount are
    robustly fitted from call-put parity for each observation/expiration; mark
    implied volatility, forward delta, and present-value vega are then computed
    with ``vanilla-option-pricers``. Expiry and time to maturity follow SPXW PM
    settlement for ``SPX`` and morning SOQ settlement for ``VIX``.
    """
    ticker = ticker.upper()
    _get_cboe_product_policy(ticker=ticker)
    missing = set(CBOE_SOURCE_COLUMNS).difference(source.columns)
    if missing:
        raise ValueError(f"missing CBOE option columns: {sorted(missing)}")
    if source.empty:
        return pd.DataFrame(columns=CBOE_SOURCE_COLUMNS)

    source = source.loc[:, list(CBOE_SOURCE_COLUMNS)].copy()
    source['date'] = pd.to_datetime(source['date'], errors='raise')
    source['exdate'] = pd.to_datetime(source['exdate'], errors='raise')
    source['cp_flag'] = source['cp_flag'].astype('string').str.upper()
    for column in (
        'strike_price',
        'mid_price',
        'bid_size',
        'best_bid',
        'offer_size',
        'best_offer',
        'open_interest',
    ):
        source[column] = pd.to_numeric(source[column], errors='coerce')

    valid_quotes = (
        source['best_bid'].ge(0.0)
        & source['best_offer'].ge(source['best_bid'])
        & source['best_bid'].notna()
        & source['best_offer'].notna()
    )
    source.loc[valid_quotes, 'mid_price'] = 0.5 * (
        source.loc[valid_quotes, 'best_bid'] + source.loc[valid_quotes, 'best_offer']
    )
    valid_contracts = source['cp_flag'].isin(('C', 'P')) & source['strike_price'].gt(0.0)
    source = source.loc[valid_contracts].copy()
    source['dte'] = _compute_cboe_ttm(source=source, ticker=ticker)
    source = source.loc[source['dte'].ge(0.0)].copy()

    normalized: list[pd.DataFrame] = []
    for (_, _), frame in source.groupby(['date', 'exdate'], observed=True, sort=False):
        result = _infer_cboe_slice_forward_discount(frame=frame)
        if result is None:
            continue
        forward, discount = map(float, result)
        ttm = float(frame['dte'].iloc[0])
        frame = frame.copy()
        frame['impl_fw'] = forward
        frame['impl_df'] = discount
        frame['mid_vols'] = _infer_cboe_mark_vols(
            frame=frame,
            forward=forward,
            discount=discount,
            ttm=ttm,
        )
        frame['delta'], frame['vega'] = _compute_cboe_mark_delta_vega(
            frame=frame,
            forward=forward,
            discount=discount,
            ttm=ttm,
        )
        normalized.append(frame)

    if not normalized:
        return pd.DataFrame(columns=CBOE_SOURCE_COLUMNS)
    return pd.concat(normalized, axis=0, ignore_index=True).loc[:, list(CBOE_SOURCE_COLUMNS)]


def _prepare_spot_data(chain_ts: pd.DataFrame,
                       spot_data: Optional[Union[pd.Series, pd.DataFrame]],
                       is_use_front_forward_as_spot: bool
                       ) -> pd.DataFrame:
    """Align supplied spot data or construct the explicitly requested proxy."""
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


def _compute_cboe_bid_ask_iv(chain_ts: pd.DataFrame) -> None:
    """Populate bid and ask implied volatility from contemporaneous prices."""
    import vanilla_option_pricers as bsm
    from numba.typed import List

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
        option_types = List(frame[SliceColumn.OPTION_TYPE.value].astype(str).tolist())
        for result, price_column in (
            (bid_iv, SliceColumn.BID_PRICE.value),
            (ask_iv, SliceColumn.ASK_PRICE.value),
        ):
            prices = frame[price_column].to_numpy(float)
            try:
                result[positions] = bsm.infer_bsm_ivols_from_slice_prices(
                    ttm=ttm,
                    forward=forward,
                    discfactor=discount,
                    strikes=strikes,
                    optiontypes=option_types,
                    model_prices=prices,
                )
            except ZeroDivisionError:
                for idx, (strike, option_type, price) in enumerate(zip(strikes, option_types, prices)):
                    try:
                        result[positions[idx]] = bsm.infer_bsm_implied_vol(
                            ttm=ttm,
                            forward=forward,
                            strike=strike,
                            optiontype=str(option_type),
                            given_price=price,
                            discfactor=discount,
                        )
                    except ZeroDivisionError:
                        result[positions[idx]] = np.nan
    chain_ts[SliceColumn.BID_IV.value] = bid_iv
    chain_ts[SliceColumn.ASK_IV.value] = ask_iv


def _finalize_cboe_options_data(chain_ts: pd.DataFrame,
                                ticker: str,
                                spot_data: Optional[Union[pd.Series, pd.DataFrame]],
                                is_use_front_forward_as_spot: bool
                                ) -> Dict[str, Any]:
    """Attach aligned spot data and source metadata to a CBOE option panel."""
    spot_data = _prepare_spot_data(
        chain_ts=chain_ts,
        spot_data=spot_data,
        is_use_front_forward_as_spot=is_use_front_forward_as_spot,
    )
    chain_ts[SliceColumn.SPOT_PRICE.value] = chain_ts[SliceColumn.EXCHANGE_TIME.value].map(spot_data['close'])
    chain_ts = _coerce_oca_options_frame(chain_ts)
    chain_ts.attrs['source'] = 'cboe_options'
    chain_ts.attrs['spot_source'] = spot_data.attrs['spot_source']
    return dict(chain_ts=chain_ts, spot_data=spot_data, ticker=ticker)


def map_cboe_options_data(source: pd.DataFrame,
                          ticker: Union[str, Literal['SPX', 'VIX']] = 'SPX',
                          spot_data: Optional[Union[pd.Series, pd.DataFrame]] = None,
                          is_use_front_forward_as_spot: bool = False
                          ) -> Dict[str, Any]:
    """Map a local CBOE SPX/VIX table to the ``OptionsDataDFs`` constructor format.

    Source observations are New York local times. ``SPX`` files contain SPXW
    contracts and use 16:00 PM expiry; ``VIX`` uses the 09:30 morning SOQ.
    Time to maturity is recomputed from those product policies instead of
    trusting the legacy fitted ``dte``. The source has no spot series or
    bid/ask implied volatilities, so those volatilities are inferred from prices
    using the contemporaneous forward, discount factor, and time to maturity.
    """
    ticker = ticker.upper()
    if ticker not in ('SPX', 'VIX'):
        raise ValueError(f"unsupported CBOE option ticker={ticker}")
    missing = set(CBOE_SOURCE_COLUMNS).difference(source.columns)
    if missing:
        raise ValueError(f"missing CBOE option columns: {sorted(missing)}")

    source = source.loc[:, list(CBOE_SOURCE_COLUMNS)].copy()
    exchange_time = _to_utc_from_new_york(source['date'])
    expiry_local = _get_cboe_expiry_local(source=source, ticker=ticker)
    expiry = _to_utc_from_new_york(expiry_local)
    ttm = (expiry - exchange_time).dt.total_seconds() / SECONDS_PER_YEAR
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
            SliceColumn.TTM.value: ttm,
            SliceColumn.CONTRACT_SIZE.value: 100.0,
            SliceColumn.DISCOUNT.value: pd.to_numeric(source['impl_df']),
        }
    )
    chain_ts = chain_ts.drop_duplicates(
        subset=[SliceColumn.EXCHANGE_TIME.value, SliceColumn.CONTRACT.value],
        keep='last',
    ).reset_index(drop=True)
    _compute_cboe_bid_ask_iv(chain_ts)
    return _finalize_cboe_options_data(
        chain_ts=chain_ts,
        ticker=ticker,
        spot_data=spot_data,
        is_use_front_forward_as_spot=is_use_front_forward_as_spot,
    )


def _iter_complete_cboe_source_frames(source_reader: Any, column_indices: list[int]):
    """Yield record-batch frames without splitting the final quote slice."""
    pending = pd.DataFrame()
    for batch_idx in range(source_reader.num_record_batches):
        source = source_reader.get_batch(batch_idx).select(column_indices).to_pandas()
        if source.index.name is not None and source.index.name not in source.columns:
            source = source.reset_index()
        if not pending.empty:
            source = pd.concat([pending, source], axis=0, ignore_index=True)
        if source.empty:
            continue
        last_date = source['date'].iloc[-1]
        last_expiry = source['exdate'].iloc[-1]
        is_pending = source['date'].eq(last_date) & source['exdate'].eq(last_expiry)
        complete = source.loc[~is_pending]
        pending = source.loc[is_pending]
        if not complete.empty:
            yield complete
    if not pending.empty:
        yield pending


def build_local_cboe_options_cache(ticker: Union[str, Literal['SPX', 'VIX']] = 'SPX',
                                   local_path: str = CBOE_FILES_LOCAL_PATH,
                                   overwrite: bool = False
                                   ) -> Path:
    """Build one normalized, compressed Parquet cache for a CBOE underlying.

    The source Feather file is processed one record batch at a time, carrying a
    quote slice across batch boundaries when necessary. Each observation/expiry
    refits parity terms and VanillaOptionPricers analytics under the product's
    settlement policy. Cache metadata records those policies, the OCA schema
    version, and the source fingerprint; stale caches are rejected.

    Parameters
    ----------
    ticker : {'SPX', 'VIX'}, default 'SPX'
        CBOE underlying to normalize.
    local_path : str, default ``CBOE_FILES_LOCAL_PATH``
        Directory containing both source files and normalized caches.
    overwrite : bool, default False
        Replace an existing cache atomically when True.

    Returns
    -------
    pathlib.Path
        Path to ``spx_options_oca.parquet`` or ``vix_options_oca.parquet``.
    """
    from uuid import uuid4

    import pyarrow as pa
    import pyarrow.ipc as ipc
    import pyarrow.parquet as pq

    ticker = ticker.upper()
    source_path = _cboe_file_path(ticker=ticker, local_path=local_path, file_names=CBOE_SOURCE_FILE_NAMES)
    cache_path = _cboe_file_path(ticker=ticker, local_path=local_path, file_names=CBOE_CACHE_FILE_NAMES)
    if cache_path.exists() and not overwrite:
        raise FileExistsError(f"CBOE cache already exists: {cache_path}")
    if not source_path.exists():
        raise FileNotFoundError(f"CBOE source file does not exist: {source_path}")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_name(f".{cache_path.name}.{uuid4().hex}.tmp")

    source_reader = ipc.RecordBatchFileReader(pa.memory_map(str(source_path), 'r'))
    missing = set(CBOE_SOURCE_COLUMNS).difference(source_reader.schema.names)
    if missing:
        raise ValueError(f"missing CBOE option columns: {sorted(missing)}")
    column_indices = [source_reader.schema.get_field_index(column) for column in CBOE_SOURCE_COLUMNS]
    cache_metadata = _cboe_cache_metadata(ticker=ticker, source_path=source_path)
    writer = None
    try:
        for source in _iter_complete_cboe_source_frames(
            source_reader=source_reader,
            column_indices=column_indices,
        ):
            source = reconstruct_cboe_source_analytics(source=source, ticker=ticker)
            if source.empty:
                continue
            chain_ts = map_cboe_options_data(source=source, ticker=ticker)['chain_ts']
            table = _to_oca_options_arrow_table(chain_ts=chain_ts, metadata=cache_metadata)
            if writer is None:
                writer = pq.ParquetWriter(
                    temporary_path,
                    table.schema,
                    compression='zstd',
                    use_dictionary=[
                        SliceColumn.UNDERLYING_INDEX.value,
                        SliceColumn.OPTION_TYPE.value,
                        SliceColumn.MATURITY_ID.value,
                    ],
                    write_statistics=True,
                )
            writer.write_table(table, row_group_size=250_000)
        if writer is None:
            raise ValueError(f"CBOE source file contains no rows: {source_path}")
        writer.close()
        writer = None
        temporary_path.replace(cache_path)
    finally:
        if writer is not None:
            writer.close()
        if temporary_path.exists():
            temporary_path.unlink()
    return cache_path


@qis.timer
def load_local_cboe_options_data(ticker: Union[str, Literal['SPX', 'VIX']] = 'SPX',
                                 local_path: str = CBOE_FILES_LOCAL_PATH,
                                 start: Optional[pd.Timestamp] = None,
                                 end: Optional[pd.Timestamp] = None,
                                 spot_data: Optional[Union[pd.Series, pd.DataFrame]] = None,
                                 is_use_front_forward_as_spot: bool = False,
                                 is_use_cache: bool = True
                                 ) -> Dict[str, Any]:
    """Load local SPX/VIX CBOE data in ``OptionsDataDFs`` format.

    A validated normalized Parquet cache is preferred when present. Without a
    cache, the selected source rows receive the same parity and BSM reconstruction
    before mapping. Set ``is_use_cache=False`` to bypass a cache explicitly.
    """
    ticker = ticker.upper()
    source_path = _cboe_file_path(ticker=ticker, local_path=local_path, file_names=CBOE_SOURCE_FILE_NAMES)
    cache_path = _cboe_file_path(ticker=ticker, local_path=local_path, file_names=CBOE_CACHE_FILE_NAMES)
    if is_use_cache and cache_path.exists():
        chain_ts = _load_cboe_cache_frame(
            cache_path=cache_path,
            ticker=ticker,
            source_path=source_path,
            start=start,
            end=end,
        )
        return _finalize_cboe_options_data(
            chain_ts=chain_ts,
            ticker=ticker,
            spot_data=spot_data,
            is_use_front_forward_as_spot=is_use_front_forward_as_spot,
        )

    source = _load_cboe_source_frame(
        file_path=source_path,
        start=start,
        end=end,
    )
    source = reconstruct_cboe_source_analytics(source=source, ticker=ticker)
    return map_cboe_options_data(
        source=source,
        ticker=ticker,
        spot_data=spot_data,
        is_use_front_forward_as_spot=is_use_front_forward_as_spot,
    )


def _tardis_eod_file_path(ticker: str, local_path: str, file_names: Dict[str, str]) -> Path:
    """Resolve one supported Tardis ticker to its source or cache file path."""
    ticker = ticker.upper()
    if ticker not in file_names:
        raise ValueError(f"unsupported Tardis EOD option ticker={ticker}")
    return Path(local_path).joinpath(file_names[ticker])


def _tardis_eod_observation_policy(daily_hour_utc: int) -> str:
    """Validate and serialize the exact daily UTC observation policy."""
    if not 0 <= daily_hour_utc <= 23:
        raise ValueError('daily_hour_utc must be between 0 and 23')
    return f'exact_{daily_hour_utc:02d}00_utc'


def _tardis_eod_cache_metadata(
    ticker: str,
    source_path: Path,
    spot_source_path: Path,
    daily_hour_utc: int,
) -> Dict[bytes, bytes]:
    """Build Tardis cache metadata and source/spot fingerprints."""
    source_stat = source_path.stat()
    spot_stat = spot_source_path.stat()
    values = {
        'oca_cache_format': TARDIS_EOD_CACHE_FORMAT,
        'oca_cache_schema_version': TARDIS_EOD_CACHE_SCHEMA_VERSION,
        'oca_dtype_policy': NORMALIZED_OPTIONS_DTYPE_POLICY,
        'oca_ticker': ticker,
        'oca_provider': 'tardis_deribit',
        'oca_frequency': 'eod',
        'oca_observation_policy': _tardis_eod_observation_policy(daily_hour_utc),
        'oca_price_convention': 'inverse_underlying_units_usd_multiplier_forward',
        'oca_spot_policy': TARDIS_EOD_SPOT_POLICY,
        'oca_settlement_policy': 'deribit_0800_utc',
        'oca_analytics': TARDIS_EOD_ANALYTICS_POLICY,
        'oca_source_file': source_path.name,
        'oca_source_size': str(source_stat.st_size),
        'oca_source_mtime_ns': str(source_stat.st_mtime_ns),
        'oca_spot_source_file': spot_source_path.name,
        'oca_spot_source_size': str(spot_stat.st_size),
        'oca_spot_source_mtime_ns': str(spot_stat.st_mtime_ns),
        'oca_created_utc': pd.Timestamp.now(tz='UTC').isoformat(),
    }
    return {key.encode(): value.encode() for key, value in values.items()}


def _validate_tardis_eod_cache(
    cache_path: Path,
    ticker: str,
    source_path: Path,
    spot_source_path: Path,
    daily_hour_utc: int,
) -> None:
    """Reject a Tardis cache whose policy, schema, or fingerprint is stale."""
    metadata = _read_cboe_cache_metadata(cache_path=cache_path)
    expected = {
        'oca_cache_format': TARDIS_EOD_CACHE_FORMAT,
        'oca_cache_schema_version': TARDIS_EOD_CACHE_SCHEMA_VERSION,
        'oca_dtype_policy': NORMALIZED_OPTIONS_DTYPE_POLICY,
        'oca_ticker': ticker,
        'oca_provider': 'tardis_deribit',
        'oca_frequency': 'eod',
        'oca_observation_policy': _tardis_eod_observation_policy(daily_hour_utc),
        'oca_price_convention': 'inverse_underlying_units_usd_multiplier_forward',
        'oca_spot_policy': TARDIS_EOD_SPOT_POLICY,
        'oca_settlement_policy': 'deribit_0800_utc',
        'oca_analytics': TARDIS_EOD_ANALYTICS_POLICY,
    }
    for prefix, path in (('oca_source', source_path), ('oca_spot_source', spot_source_path)):
        if path.exists():
            stat = path.stat()
            expected.update(
                {
                    f'{prefix}_file': path.name,
                    f'{prefix}_size': str(stat.st_size),
                    f'{prefix}_mtime_ns': str(stat.st_mtime_ns),
                }
            )
    mismatches = {
        key: (metadata.get(key), value)
        for key, value in expected.items()
        if metadata.get(key) != value
    }
    if mismatches:
        details = ', '.join(
            f"{key}={actual!r} (expected {expected_value!r})"
            for key, (actual, expected_value) in mismatches.items()
        )
        raise ValueError(
            f'incompatible or stale Tardis EOD cache {cache_path}: {details}. '
            'Rebuild it with build_local_tardis_eod_options_cache(..., overwrite=True).'
        )


def _load_tardis_spot_series(spot_source_path: Path) -> pd.Series:
    """Load and clean the exact-time Deribit index-price series."""
    spot = pd.read_feather(spot_source_path, columns=['timestamp', 'index_price'])
    spot['timestamp'] = pd.to_datetime(spot['timestamp'], utc=True)
    spot['index_price'] = pd.to_numeric(spot['index_price'], errors='coerce')
    spot = spot.dropna(subset=['timestamp', 'index_price']).drop_duplicates('timestamp', keep='last')
    return spot.set_index('timestamp')['index_price'].sort_index()


def _map_tardis_eod_options_data(source: pd.DataFrame, ticker: str, spot: pd.Series) -> pd.DataFrame:
    """Map filtered Tardis rows to the canonical ``SliceColumn`` schema."""
    missing = set(TARDIS_EOD_SOURCE_COLUMNS).difference(source.columns)
    if missing:
        raise ValueError(f"missing Tardis option columns: {sorted(missing)}")

    exchange_time = pd.to_datetime(source['exchange_time'], utc=True)
    expiry = pd.to_datetime(source['expiry'], utc=True)
    option_type = source['optiontype'].astype('string').str.upper()
    if option_type.isna().any() or not option_type.isin(('C', 'P')).all():
        raise ValueError(f"unsupported option types: {sorted(option_type.dropna().unique())}")
    ttm = ((expiry - exchange_time).dt.total_seconds() / SECONDS_PER_YEAR).clip(lower=0.0)
    spot_price = exchange_time.map(spot)
    if spot_price.isna().any():
        is_index_price = source['underlying_index'].astype('string').eq('index_price')
        option_spot = pd.DataFrame(
            {
                'exchange_time': exchange_time.loc[is_index_price],
                'underlying_price': pd.to_numeric(
                    source.loc[is_index_price, 'underlying_price'],
                    errors='coerce',
                ),
            }
        ).groupby('exchange_time', observed=True)['underlying_price'].median()
        spot_price = spot_price.fillna(exchange_time.map(option_spot))
    if spot_price.isna().any():
        missing_times = exchange_time.loc[spot_price.isna()].drop_duplicates().sort_values()
        preview = ', '.join(str(value) for value in missing_times.iloc[:3])
        raise ValueError(f'missing exact Tardis index price for {len(missing_times.index)} observations: {preview}')

    chain_ts = pd.DataFrame(
        {
            SliceColumn.CONTRACT.value: source['contract'],
            SliceColumn.EXCHANGE_TIME.value: exchange_time,
            SliceColumn.UNDERLYING_INDEX.value: source['underlying_index'],
            SliceColumn.FORWARD_PRICE.value: source['underlying_price'],
            SliceColumn.SPOT_PRICE.value: spot_price,
            SliceColumn.USD_MULTIPLIER.value: source['usd_multiplier'],
            SliceColumn.MARK_PRICE.value: source['mark_price'],
            SliceColumn.BID_PRICE.value: source['bid_price'],
            SliceColumn.ASK_PRICE.value: source['ask_price'],
            SliceColumn.BID_SIZE.value: source['bid_size'],
            SliceColumn.ASK_SIZE.value: source['ask_size'],
            SliceColumn.MARK_IV.value: source['mark_iv'],
            SliceColumn.BID_IV.value: source['bid_iv'],
            SliceColumn.ASK_IV.value: source['ask_iv'],
            SliceColumn.DELTA.value: source['delta'],
            SliceColumn.VEGA.value: source['vega'],
            SliceColumn.THETA.value: source['theta'],
            SliceColumn.GAMMA.value: source['gamma'],
            SliceColumn.OPEN_INTEREST.value: source['open_interest'],
            SliceColumn.VOLUME.value: source['volume'],
            SliceColumn.MATURITY_ID.value: expiry.dt.strftime('%d%b%Y'),
            SliceColumn.STRIKE.value: source['strike'],
            SliceColumn.OPTION_TYPE.value: option_type,
            SliceColumn.EXPIRY.value: expiry,
            SliceColumn.TTM.value: ttm,
            SliceColumn.CONTRACT_SIZE.value: source['contract_size'],
            SliceColumn.DISCOUNT.value: 1.0,
        }
    )
    chain_ts = chain_ts.drop_duplicates(
        subset=[SliceColumn.EXCHANGE_TIME.value, SliceColumn.CONTRACT.value],
        keep='last',
    )
    return _coerce_oca_options_frame(chain_ts)


def build_local_tardis_eod_options_cache(
    ticker: Union[str, Literal['BTC', 'ETH']] = 'BTC',
    local_path: str = TARDIS_FILES_LOCAL_PATH,
    daily_hour_utc: int = TARDIS_EOD_HOUR_UTC,
    overwrite: bool = False,
) -> Path:
    """Build one exact-time daily BTC/ETH option cache from the hourly Tardis archive.

    The selected observation is exactly ``daily_hour_utc:00 UTC``; no prior or
    future quote is substituted. Deribit inverse option prices remain in units
    of BTC/ETH and ``usd_multiplier`` remains the contemporaneous forward.
    ``spot_price`` is the exact-time Deribit index price and ``discount`` is one,
    preserving the legacy Tardis normalization convention.
    """
    from uuid import uuid4

    import pyarrow as pa
    import pyarrow.ipc as ipc
    import pyarrow.parquet as pq

    ticker = ticker.upper()
    _tardis_eod_observation_policy(daily_hour_utc)
    source_path = _tardis_eod_file_path(ticker, local_path, TARDIS_EOD_SOURCE_FILE_NAMES)
    spot_source_path = _tardis_eod_file_path(ticker, local_path, TARDIS_EOD_SPOT_FILE_NAMES)
    cache_path = _tardis_eod_file_path(ticker, local_path, TARDIS_EOD_CACHE_FILE_NAMES)
    if cache_path.exists() and not overwrite:
        raise FileExistsError(f'Tardis EOD cache already exists: {cache_path}')
    for path in (source_path, spot_source_path):
        if not path.exists():
            raise FileNotFoundError(f'Tardis source file does not exist: {path}')

    source_reader = ipc.RecordBatchFileReader(pa.memory_map(str(source_path), 'r'))
    missing = set(TARDIS_EOD_SOURCE_COLUMNS).difference(source_reader.schema.names)
    if missing:
        raise ValueError(f"missing Tardis option columns: {sorted(missing)}")
    column_indices = [source_reader.schema.get_field_index(column) for column in TARDIS_EOD_SOURCE_COLUMNS]
    frames = []
    for batch_idx in range(source_reader.num_record_batches):
        frame = source_reader.get_batch(batch_idx).select(column_indices).to_pandas()
        exchange_time = pd.to_datetime(frame['exchange_time'], utc=True)
        is_eod = (
            exchange_time.dt.hour.eq(daily_hour_utc)
            & exchange_time.dt.minute.eq(0)
            & exchange_time.dt.second.eq(0)
        )
        if is_eod.any():
            frames.append(frame.loc[is_eod].copy())
    if not frames:
        raise ValueError(f'Tardis source has no exact {_tardis_eod_observation_policy(daily_hour_utc)} rows')

    chain_ts = _map_tardis_eod_options_data(
        source=pd.concat(frames, axis=0, ignore_index=True),
        ticker=ticker,
        spot=_load_tardis_spot_series(spot_source_path),
    ).sort_values(
        [
            SliceColumn.EXCHANGE_TIME.value,
            SliceColumn.EXPIRY.value,
            SliceColumn.STRIKE.value,
            SliceColumn.OPTION_TYPE.value,
            SliceColumn.CONTRACT.value,
        ]
    ).reset_index(drop=True)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_name(f'.{cache_path.name}.{uuid4().hex}.tmp')
    metadata = _tardis_eod_cache_metadata(ticker, source_path, spot_source_path, daily_hour_utc)
    table = _to_oca_options_arrow_table(chain_ts=chain_ts, metadata=metadata)
    try:
        pq.write_table(
            table,
            temporary_path,
            compression='zstd',
            use_dictionary=list(OCA_STRING_COLUMNS),
            write_statistics=True,
            row_group_size=250_000,
        )
        temporary_path.replace(cache_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return cache_path


def _to_tardis_cache_utc(timestamp: Optional[pd.Timestamp], is_end: bool = False) -> Optional[pd.Timestamp]:
    """Normalize a Tardis cache filter boundary to timezone-aware UTC."""
    if timestamp is None:
        return None
    timestamp = pd.Timestamp(timestamp)
    is_date = timestamp == timestamp.normalize()
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize('UTC')
    else:
        timestamp = timestamp.tz_convert('UTC')
    if is_end and is_date:
        timestamp = timestamp + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return timestamp


def _finalize_tardis_eod_options_data(chain_ts: pd.DataFrame, ticker: str) -> Dict[str, Any]:
    """Create aligned spot data and source metadata for a Tardis EOD panel."""
    chain_ts = _coerce_oca_options_frame(chain_ts)
    exchange_time = SliceColumn.EXCHANGE_TIME.value
    spot_price = SliceColumn.SPOT_PRICE.value
    spot_data = (
        chain_ts[[exchange_time, spot_price]]
        .dropna(subset=[spot_price])
        .drop_duplicates(exchange_time, keep='last')
        .set_index(exchange_time)[spot_price]
        .sort_index()
        .rename('close')
        .to_frame()
    )
    spot_data.attrs['spot_source'] = 'cached_exact_tardis_index_price'
    chain_ts.attrs['source'] = 'tardis_deribit_eod'
    chain_ts.attrs['spot_source'] = spot_data.attrs['spot_source']
    return dict(chain_ts=chain_ts, spot_data=spot_data, ticker=ticker)


@qis.timer
def load_local_tardis_eod_options_data(
    ticker: Union[str, Literal['BTC', 'ETH']] = 'BTC',
    local_path: str = TARDIS_FILES_LOCAL_PATH,
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
    daily_hour_utc: int = TARDIS_EOD_HOUR_UTC,
) -> Dict[str, Any]:
    """Load a validated exact-time BTC/ETH EOD cache in ``OptionsDataDFs`` format."""
    ticker = ticker.upper()
    source_path = _tardis_eod_file_path(ticker, local_path, TARDIS_EOD_SOURCE_FILE_NAMES)
    spot_source_path = _tardis_eod_file_path(ticker, local_path, TARDIS_EOD_SPOT_FILE_NAMES)
    cache_path = _tardis_eod_file_path(ticker, local_path, TARDIS_EOD_CACHE_FILE_NAMES)
    if not cache_path.exists():
        raise FileNotFoundError(
            f'Tardis EOD cache does not exist: {cache_path}. '
            'Build it with build_local_tardis_eod_options_cache(...).'
        )
    _validate_tardis_eod_cache(cache_path, ticker, source_path, spot_source_path, daily_hour_utc)

    filters = []
    exchange_time = SliceColumn.EXCHANGE_TIME.value
    start_utc = _to_tardis_cache_utc(start)
    end_utc = _to_tardis_cache_utc(end, is_end=True)
    if start_utc is not None:
        filters.append((exchange_time, '>=', start_utc))
    if end_utc is not None:
        filters.append((exchange_time, '<=', end_utc))
    chain_ts = pd.read_parquet(
        cache_path,
        columns=[column.value for column in SliceColumn],
        filters=filters or None,
    ).reset_index(drop=True)
    return _finalize_tardis_eod_options_data(chain_ts=chain_ts, ticker=ticker)


class UnitTests(Enum):
    """Runnable local loader diagnostic cases."""

    LOAD_TARDIS_OPTIONS_DF = 1
    LOAD_DERIBIT_OPTIONS_DF = 2


def run_unit_test(unit_test: UnitTests):
    """Run the selected local Tardis or Deribit loader diagnostic."""

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
