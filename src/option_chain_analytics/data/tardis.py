"""Normalize local Tardis/Deribit histories and build exact-time EOD caches.

The source archive contains hourly BTC and ETH option observations plus their
perpetual/index histories. ``load_local_tardis_contract_ts_data`` preserves the
historical in-memory format used by SigmaStrats research. The standardized path
selects observations exactly at a configured UTC hour and writes one canonical
Parquet cache per ticker for repeatable point-in-time studies.

Inverse option prices remain in units of the underlying coin. ``usd_multiplier``
is the contemporaneous expiry forward, ``spot_price`` is selected at the exact
observation time, and the legacy Tardis discount convention is one. No nearest,
backward-filled, or future spot observation is substituted. Raw archives and
derived caches are local research data and are never distributed with OCA.
"""

from pathlib import Path
from typing import Any, Dict, Literal, Optional, Union

import pandas as pd
import qis

from option_chain_analytics import local_path as lp
from option_chain_analytics.data.cache import (
    NORMALIZED_OPTIONS_CACHE_FORMAT,
    NORMALIZED_OPTIONS_CACHE_SCHEMA_VERSION,
    NORMALIZED_OPTIONS_DTYPE_POLICY,
    OCA_STRING_COLUMNS,
    _coerce_oca_options_frame,
    _normalized_cache_directory,
    _read_cache_metadata,
    _to_oca_options_arrow_table,
)
from option_chain_analytics.option_chain import SliceColumn

TARDIS_FILES_LOCAL_PATH = f"{lp.get_resource_path()}tardis\\"
TARDIS_EOD_CACHE_LOCAL_PATH = f"{lp.get_cache_path()}tardis\\"

TARDIS_EOD_CACHE_FORMAT = NORMALIZED_OPTIONS_CACHE_FORMAT
TARDIS_EOD_CACHE_SCHEMA_VERSION = NORMALIZED_OPTIONS_CACHE_SCHEMA_VERSION
TARDIS_EOD_ANALYTICS_POLICY = 'provider_iv_greeks_discount_one'
TARDIS_EOD_SPOT_POLICY = 'exact_perpetual_index_then_option_index'
TARDIS_EOD_SOURCE_FILE_NAMES = {'BTC': 'BTC_freq_H.feather', 'ETH': 'ETH_freq_H.feather'}
TARDIS_EOD_SPOT_FILE_NAMES = {'BTC': 'BTC_perp_freq_H.feather', 'ETH': 'ETH_perp_freq_H.feather'}
TARDIS_EOD_CACHE_FILE_NAMES = {'BTC': 'btc_options_oca.parquet', 'ETH': 'eth_options_oca.parquet'}
TARDIS_EOD_HOUR_UTC = 8
SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0

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

@qis.timer
def load_local_tardis_contract_ts_data(ticker: str = 'BTC',
                                       local_path: str = TARDIS_FILES_LOCAL_PATH
                                       ) -> Dict[str, Any]:
    """Load the maintainer-format hourly Tardis option and perpetual histories.

    Parameters
    ----------
    ticker : str, default 'BTC'
        Crypto option root. Existing local archives support ``BTC`` and ``ETH``.
    local_path : str, default TARDIS_FILES_LOCAL_PATH
        Directory containing ``<ticker>_freq_H.feather`` and
        ``<ticker>_perp_freq_H.feather``.

    Returns
    -------
    dict[str, Any]
        Original hourly ``chain_ts``, timestamp-indexed perpetual ``spot_data``,
        and ``ticker`` for ``OptionsDataDFs(**result)``.

    Notes
    -----
    This is a local archive adapter, not a redistributable dataset. It adds the
    historical ``forward_price`` alias when older files contain only
    ``underlying_price``; it otherwise leaves the stored observations unchanged.
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

def _tardis_eod_file_path(ticker: str, local_path: str, file_names: Dict[str, str]) -> Path:
    """Resolve one supported Tardis ticker to its source or cache file path."""
    ticker = ticker.upper()
    if ticker not in file_names:
        raise ValueError(f"unsupported Tardis EOD option ticker={ticker}")
    return Path(local_path).joinpath(file_names[ticker])


def _tardis_eod_cache_path(ticker: str, local_path: str) -> Path:
    """Resolve a Tardis EOD cache centrally while preserving custom paths."""
    cache_directory = _normalized_cache_directory(
        local_path=local_path,
        default_source_path=TARDIS_FILES_LOCAL_PATH,
        default_cache_path=TARDIS_EOD_CACHE_LOCAL_PATH,
    )
    return _tardis_eod_file_path(ticker, cache_directory, TARDIS_EOD_CACHE_FILE_NAMES)


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
    metadata = _read_cache_metadata(cache_path=cache_path)
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

    Parameters
    ----------
    ticker : {'BTC', 'ETH'}, default 'BTC'
        Underlying whose hourly option and perpetual files are normalized.
    local_path : str, default TARDIS_FILES_LOCAL_PATH
        Directory containing the local source Feather files. The default writes
        caches below ``OCA_CACHE_PATH/tardis``; custom paths remain co-located.
    daily_hour_utc : int, default TARDIS_EOD_HOUR_UTC
        Exact UTC hour retained from every available day.
    overwrite : bool, default False
        Atomically replace an existing compatible target when ``True``.

    Returns
    -------
    pathlib.Path
        Path to the normalized BTC or ETH Parquet cache.

    Raises
    ------
    FileNotFoundError
        If either required source archive is absent.
    ValueError
        If the source schema is incomplete or contains no rows at the exact
        requested observation hour.
    """
    from uuid import uuid4

    import pyarrow as pa
    import pyarrow.ipc as ipc
    import pyarrow.parquet as pq

    ticker = ticker.upper()
    _tardis_eod_observation_policy(daily_hour_utc)
    source_path = _tardis_eod_file_path(ticker, local_path, TARDIS_EOD_SOURCE_FILE_NAMES)
    spot_source_path = _tardis_eod_file_path(ticker, local_path, TARDIS_EOD_SPOT_FILE_NAMES)
    cache_path = _tardis_eod_cache_path(ticker, local_path)
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
    """Load a validated exact-time BTC/ETH cache with optional UTC bounds.

    Parameters
    ----------
    ticker : {'BTC', 'ETH'}, default 'BTC'
        Cached crypto option root.
    local_path : str, default TARDIS_FILES_LOCAL_PATH
        Source directory used to resolve and fingerprint the normalized cache.
    start, end : pandas.Timestamp, optional
        Inclusive UTC observation bounds. Date-only ``end`` values include the
        complete final calendar day.
    daily_hour_utc : int, default TARDIS_EOD_HOUR_UTC
        Exact observation hour encoded by the cache and validated on load.

    Returns
    -------
    dict[str, Any]
        Canonical ``chain_ts``, aligned exact-time ``spot_data``, and ``ticker``
        for ``OptionsDataDFs(**result)``.

    Raises
    ------
    FileNotFoundError
        If the normalized cache has not been built.
    ValueError
        If schema, policy, or source fingerprints do not match the request.
    """
    ticker = ticker.upper()
    source_path = _tardis_eod_file_path(ticker, local_path, TARDIS_EOD_SOURCE_FILE_NAMES)
    spot_source_path = _tardis_eod_file_path(ticker, local_path, TARDIS_EOD_SPOT_FILE_NAMES)
    cache_path = _tardis_eod_cache_path(ticker, local_path)
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
