"""Normalize local CBOE SPX and VIX histories into auditable OCA panels.

The adapter consumes the maintainer's daily fitted-chain Feather files, but it
does not trust their legacy fitted forward, discount, or volatility fields.
For every observation/expiry slice it rebuilds the quote midpoint, robustly
infers forward and discount from call-put parity, and computes implied
volatility, forward delta, and present-value vega with
``vanilla-option-pricers``.

Product conventions are explicit. SPX is treated as PM-settled SPXW at 16:00
New York, whereas VIX uses its 09:30 New York morning SOQ. Observation and
expiry timestamps are converted to UTC before the complete ``SliceColumn``
schema is produced. CBOE files contain no independent spot history; callers
must supply one for return studies or explicitly request the front-forward
visualization proxy.

``build_local_cboe_options_cache`` streams large sources into fingerprinted,
Zstandard-compressed Parquet without splitting a quote slice across batches.
``load_local_cboe_options_data`` validates and predicate-filters that cache, or
applies the identical reconstruction path directly to bounded source rows.
Neither the licensed source files nor normalized caches are distributed.
"""

from pathlib import Path
from typing import Any, Dict, Literal, Optional, Union

import numpy as np
import pandas as pd
import qis

from option_chain_analytics import local_path as lp
from option_chain_analytics.data.cache import (
    NORMALIZED_OPTIONS_CACHE_FORMAT,
    NORMALIZED_OPTIONS_CACHE_SCHEMA_VERSION,
    NORMALIZED_OPTIONS_DTYPE_POLICY,
    _coerce_oca_options_frame,
    _normalized_cache_directory,
    _read_cache_metadata,
    _to_oca_options_arrow_table,
)
from option_chain_analytics.option_chain import SliceColumn

CBOE_FILES_LOCAL_PATH = f"{lp.get_resource_path()}cboe_options\\"
CBOE_CACHE_LOCAL_PATH = f"{lp.get_cache_path()}cboe_options\\"

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
SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0

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

def _cboe_cache_path(ticker: str, local_path: str) -> Path:
    """Resolve a CBOE cache centrally while preserving custom co-located paths."""
    cache_directory = _normalized_cache_directory(
        local_path=local_path,
        default_source_path=CBOE_FILES_LOCAL_PATH,
        default_cache_path=CBOE_CACHE_LOCAL_PATH,
    )
    return _cboe_file_path(ticker=ticker, local_path=cache_directory, file_names=CBOE_CACHE_FILE_NAMES)


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


def _validate_cboe_cache(cache_path: Path, ticker: str, source_path: Path) -> None:
    """Reject a CBOE cache whose policy, schema, or fingerprint is stale."""
    metadata = _read_cache_metadata(cache_path=cache_path)
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
    from option_chain_analytics.utils.forward_discount import imply_forward_discount_from_bid_ask_prices

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

    Parameters
    ----------
    source : pandas.DataFrame
        CBOE source rows containing every field in ``CBOE_SOURCE_COLUMNS``.
        ``date`` and ``exdate`` are interpreted under the provider's New York
        local-time convention.
    ticker : {'SPX', 'VIX'}, default 'SPX'
        Product policy used for expiry time and contract validation.

    Returns
    -------
    pandas.DataFrame
        A source-shaped copy with reconstructed ``mid_price``, ``impl_fw``,
        ``impl_df``, ``mid_vols``, ``delta``, ``vega``, and year-fraction ``dte``.
        Slices without a valid parity fit are omitted.

    Raises
    ------
    ValueError
        If ``ticker`` is unsupported or required source columns are missing.
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

    Parameters
    ----------
    source : pandas.DataFrame
        Reconstructed CBOE rows, normally returned by
        :func:`reconstruct_cboe_source_analytics`.
    ticker : {'SPX', 'VIX'}, default 'SPX'
        CBOE product whose settlement and contract-size conventions are applied.
    spot_data : pandas.Series or pandas.DataFrame, optional
        Independently sourced spot history. A series is interpreted as ``close``;
        a frame must expose or be reducible to the same aligned price column.
    is_use_front_forward_as_spot : bool, default False
        Construct an explicitly labelled front-forward proxy when independent
        spot is unavailable. This is intended for visualization, not returns.

    Returns
    -------
    dict[str, Any]
        Complete canonical ``chain_ts``, aligned ``spot_data``, and ``ticker``
        suitable for ``OptionsDataDFs(**result)``.

    Raises
    ------
    ValueError
        If the product, source schema, or option-type values are unsupported.
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
        Directory containing source files. With the default source path, the
        normalized cache is written under ``OCA_CACHE_PATH/cboe_options``;
        custom directories retain co-located source and cache files.
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
    cache_path = _cboe_cache_path(ticker=ticker, local_path=local_path)
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

    Parameters
    ----------
    ticker : {'SPX', 'VIX'}, default 'SPX'
        CBOE option root to load.
    local_path : str, default CBOE_FILES_LOCAL_PATH
        Directory containing the source Feather file. With the configured
        default, normalized caches resolve separately below ``OCA_CACHE_PATH``.
    start, end : pandas.Timestamp, optional
        Inclusive observation bounds. Naive values are interpreted in New York
        source time; aware values are converted to New York before source reads
        and to UTC for normalized-cache filters.
    spot_data : pandas.Series or pandas.DataFrame, optional
        Independent spot observations to align to option report timestamps.
    is_use_front_forward_as_spot : bool, default False
        Use the front expiry forward as an explicitly labelled plotting proxy
        when no independent spot series is supplied.
    is_use_cache : bool, default True
        Prefer a present, compatible normalized Parquet cache. ``False`` forces
        reconstruction from the source file for the requested window.

    Returns
    -------
    dict[str, Any]
        Canonical ``chain_ts``, aligned ``spot_data``, and ``ticker`` suitable
        for ``OptionsDataDFs(**result)``.

    Raises
    ------
    FileNotFoundError
        If neither the selected source path nor required cache input is present.
    ValueError
        If a cache fingerprint/policy is stale or source normalization fails.
    """
    ticker = ticker.upper()
    source_path = _cboe_file_path(ticker=ticker, local_path=local_path, file_names=CBOE_SOURCE_FILE_NAMES)
    cache_path = _cboe_cache_path(ticker=ticker, local_path=local_path)
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
