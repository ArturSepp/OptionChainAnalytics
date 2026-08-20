"""Partitioned local caches for normalized ThetaData EOD option history."""

from __future__ import annotations

import json
import os
import uuid
from calendar import monthrange
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from option_chain_analytics import local_path as lp
from option_chain_analytics.data.cache import (
    NORMALIZED_OPTIONS_CACHE_FORMAT,
    NORMALIZED_OPTIONS_CACHE_SCHEMA_VERSION,
    NORMALIZED_OPTIONS_DTYPE_POLICY,
    _coerce_oca_options_frame,
    _to_oca_options_arrow_table,
)
from option_chain_analytics.data.thetadata import map_thetadata_eod_options_data
from option_chain_analytics.option_chain import SliceColumn
from option_chain_analytics.option_data import OptionsDataDFs

CACHE_FORMAT = 'option_chain_analytics.thetadata_eod.partitioned'
CACHE_VERSION = '1'
PROVIDER = 'thetadata_option_eod'
ANALYTICS_POLICY = 'parity_huber_vip_bsm'
CONFIGURATION_IDENTITY_KEYS = (
    'cache_format',
    'cache_version',
    'oca_cache_format',
    'oca_schema_version',
    'oca_dtype_policy',
    'provider',
    'ticker',
    'min_dte',
    'max_dte',
    'strike_range',
    'liquidity_threshold',
    'rate_policy',
    'analytics_policy',
)


def _as_date(value: date | str, name: str) -> date:
    try:
        return value if isinstance(value, date) else date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{name} must be an ISO date') from exc


def _month_windows(start_date: date, end_date: date) -> Iterator[tuple[date, date]]:
    cursor = start_date.replace(day=1)
    while cursor <= end_date:
        month_end = cursor.replace(day=monthrange(cursor.year, cursor.month)[1])
        yield max(start_date, cursor), min(end_date, month_end)
        cursor = (month_end + timedelta(days=1)).replace(day=1)


def _cache_root(ticker: str, output_dir: str | Path | None) -> Path:
    if output_dir is not None:
        return Path(output_dir).expanduser().resolve()
    return Path(lp.get_cache_path()).joinpath('thetadata_options', ticker.lower()).resolve()


def _configuration(
    *,
    ticker: str,
    start_date: date,
    end_date: date,
    min_dte: int,
    max_dte: int,
    strike_range: int | None,
    liquidity_threshold: float,
) -> dict[str, Any]:
    return {
        'cache_format': CACHE_FORMAT,
        'cache_version': CACHE_VERSION,
        'oca_cache_format': NORMALIZED_OPTIONS_CACHE_FORMAT,
        'oca_schema_version': NORMALIZED_OPTIONS_CACHE_SCHEMA_VERSION,
        'oca_dtype_policy': NORMALIZED_OPTIONS_DTYPE_POLICY,
        'provider': PROVIDER,
        'ticker': ticker,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'min_dte': min_dte,
        'max_dte': max_dte,
        'strike_range': strike_range,
        'liquidity_threshold': liquidity_threshold,
        'rate_policy': 'parity_only',
        'analytics_policy': ANALYTICS_POLICY,
    }


def _configuration_is_compatible(existing: Any, requested: dict[str, Any]) -> bool:
    """Allow date-range extension while holding data and analytics policy fixed."""
    if not isinstance(existing, dict):
        return False
    return all(existing.get(key) == requested.get(key) for key in CONFIGURATION_IDENTITY_KEYS)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_table_atomic(table: Any, path: Path) -> None:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ImportError(
            'ThetaData Parquet caching requires PyArrow; install '
            '`pip install "option-chain-analytics[thetadata,cboe]"`.'
        ) from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        pq.write_table(table, temporary, compression='zstd', row_group_size=250_000)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _metadata(configuration: dict[str, Any], period_start: date, period_end: date) -> dict[bytes, bytes]:
    values = {
        'oca_cache_format': configuration['oca_cache_format'],
        'oca_cache_schema_version': configuration['oca_schema_version'],
        'oca_dtype_policy': configuration['oca_dtype_policy'],
        'provider': configuration['provider'],
        'ticker': configuration['ticker'],
        'period_start': period_start.isoformat(),
        'period_end': period_end.isoformat(),
        'min_dte': str(configuration['min_dte']),
        'max_dte': str(configuration['max_dte']),
        'strike_range': str(configuration['strike_range']),
        'rate_policy': configuration['rate_policy'],
        'analytics_policy': configuration['analytics_policy'],
    }
    return {key.encode(): value.encode() for key, value in values.items()}


def _partition_is_valid(path: Path, expected_metadata: dict[bytes, bytes]) -> bool:
    if not path.is_file():
        return False
    try:
        import pyarrow.parquet as pq

        metadata = pq.read_schema(path).metadata or {}
    except Exception:
        return False
    return all(metadata.get(key) == value for key, value in expected_metadata.items())


def _filter_dte(option_source: pd.DataFrame, min_dte: int, max_dte: int) -> pd.DataFrame:
    if option_source.empty:
        return option_source
    expiration = pd.to_datetime(option_source['expiration'], errors='raise').dt.normalize()
    report_date = (
        pd.to_datetime(option_source['created'], utc=True, errors='raise')
        .dt.tz_convert('America/New_York')
        .dt.tz_localize(None)
        .dt.normalize()
    )
    dte = (expiration - report_date).dt.days
    return option_source.loc[dte.between(min_dte, max_dte)].copy()


def _spot_arrow_table(spot_data: pd.DataFrame, metadata: dict[bytes, bytes]) -> Any:
    import pyarrow as pa

    frame = spot_data.reset_index()
    frame[SliceColumn.EXCHANGE_TIME.value] = pd.to_datetime(
        frame[SliceColumn.EXCHANGE_TIME.value], utc=True
    )
    frame['close'] = pd.to_numeric(frame['close'], errors='raise').astype('float64')
    schema = pa.schema(
        [
            pa.field(SliceColumn.EXCHANGE_TIME.value, pa.timestamp('ns', tz='UTC')),
            pa.field('close', pa.float64()),
        ]
    )
    table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False, safe=True)
    return table.replace_schema_metadata({**(table.schema.metadata or {}), **metadata})


def _create_client() -> Any:
    try:
        from thetadata import ThetaClient
    except ImportError as exc:
        raise ImportError(
            'Install the official client with '
            '`pip install "option-chain-analytics[thetadata,cboe]"`.'
        ) from exc
    return ThetaClient(dataframe_type='pandas')


def build_thetadata_eod_cache(
    ticker: str = 'SPY',
    start_date: date | str = date(2023, 6, 1),
    end_date: date | str | None = None,
    *,
    output_dir: str | Path | None = None,
    min_dte: int = 0,
    max_dte: int = 60,
    strike_range: int | None = 20,
    liquidity_threshold: float = 1.0,
    overwrite: bool = False,
    client: Any | None = None,
) -> Path:
    """Build or resume a normalized, monthly partitioned ThetaData EOD cache.

    Existing compatible partitions are skipped. The default location is
    ``$OCA_CACHE_PATH/thetadata_options/<ticker>/`` and the default end date is
    yesterday, compatible with ThetaData's free delayed access.
    """
    ticker = ticker.strip().upper()
    report_start = _as_date(start_date, 'start_date')
    report_end = _as_date(end_date or (date.today() - timedelta(days=1)), 'end_date')
    if not ticker:
        raise ValueError('ticker must not be empty')
    if report_start > report_end:
        raise ValueError('start_date must not be after end_date')
    if min_dte < 0 or max_dte < min_dte:
        raise ValueError('require 0 <= min_dte <= max_dte')
    if strike_range is not None and strike_range < 1:
        raise ValueError('strike_range must be positive or None')
    if liquidity_threshold <= 0.0:
        raise ValueError('liquidity_threshold must be positive')

    configuration = _configuration(
        ticker=ticker,
        start_date=report_start,
        end_date=report_end,
        min_dte=min_dte,
        max_dte=max_dte,
        strike_range=strike_range,
        liquidity_threshold=liquidity_threshold,
    )
    cache_root = _cache_root(ticker=ticker, output_dir=output_dir)
    manifest_path = cache_root.joinpath('manifest.json')
    if manifest_path.is_file() and not overwrite:
        existing = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not _configuration_is_compatible(existing.get('configuration'), configuration):
            raise ValueError(
                f'incompatible ThetaData cache configuration at {cache_root}; '
                'choose another output directory or pass overwrite=True'
            )

    provider = client if client is not None else _create_client()
    owns_client = client is None
    completed: list[dict[str, Any]] = []
    try:
        for period_start, period_end in _month_windows(report_start, report_end):
            partition_id = f'{period_start:%Y-%m}'
            options_path = cache_root.joinpath('options', f'{partition_id}.parquet')
            spot_path = cache_root.joinpath('spot', f'{partition_id}.parquet')
            metadata = _metadata(configuration, period_start, period_end)
            if (
                not overwrite
                and _partition_is_valid(options_path, metadata)
                and _partition_is_valid(spot_path, metadata)
            ):
                print(f'{partition_id}: cached', flush=True)
                completed.append({'partition': partition_id, 'status': 'cached'})
                continue

            print(f'{partition_id}: requesting bulk EOD', flush=True)
            request_kwargs: dict[str, Any] = {
                'start_date': period_start,
                'end_date': period_end,
                'symbol': ticker,
                'expiration': '*',
                'max_dte': max_dte,
            }
            if strike_range is not None:
                request_kwargs['strike_range'] = strike_range
            option_source = provider.option_history_eod(**request_kwargs)
            if not isinstance(option_source, pd.DataFrame):
                raise TypeError('ThetaData client must be configured with dataframe_type="pandas"')
            option_source = _filter_dte(option_source, min_dte=min_dte, max_dte=max_dte)
            if option_source.empty:
                raise ValueError(f'no {ticker} option EOD rows returned for {partition_id}')

            spot_source = provider.stock_history_eod(
                symbol=ticker,
                start_date=period_start,
                end_date=period_end,
            )
            if not isinstance(spot_source, pd.DataFrame):
                raise TypeError('ThetaData client must be configured with dataframe_type="pandas"')
            mapped = map_thetadata_eod_options_data(
                option_source=option_source,
                spot_source=spot_source,
                ticker=ticker,
                rate_source=None,
                liquidity_threshold=liquidity_threshold,
            )
            if mapped['chain_ts'].empty:
                raise ValueError(f'OCA normalization retained no rows for {partition_id}')

            options_table = _to_oca_options_arrow_table(mapped['chain_ts'], metadata)
            spot_table = _spot_arrow_table(mapped['spot_data'], metadata)
            _write_table_atomic(options_table, options_path)
            _write_table_atomic(spot_table, spot_path)
            result = {
                'partition': partition_id,
                'status': 'written',
                'option_rows': options_table.num_rows,
                'spot_rows': spot_table.num_rows,
            }
            completed.append(result)
            print(
                f"{partition_id}: wrote {result['option_rows']:,} options and "
                f"{result['spot_rows']:,} spot rows",
                flush=True,
            )
            _write_json_atomic(
                manifest_path,
                {
                    'configuration': configuration,
                    'updated_at_utc': datetime.now(timezone.utc).isoformat(),
                    'completed': completed,
                },
            )
    finally:
        if owns_client and hasattr(provider, 'close'):
            provider.close()

    _write_json_atomic(
        manifest_path,
        {
            'configuration': configuration,
            'updated_at_utc': datetime.now(timezone.utc).isoformat(),
            'completed': completed,
        },
    )
    return cache_root


def _select_partitions(paths: list[Path], start_date: date | None, end_date: date | None) -> list[Path]:
    selected: list[Path] = []
    for path in paths:
        try:
            partition_month = date.fromisoformat(f'{path.stem}-01')
        except ValueError:
            continue
        partition_end = partition_month.replace(day=monthrange(partition_month.year, partition_month.month)[1])
        if start_date is not None and partition_end < start_date:
            continue
        if end_date is not None and partition_month > end_date:
            continue
        selected.append(path)
    return selected


def _filter_report_dates(frame: pd.DataFrame, start_date: date | None, end_date: date | None) -> pd.DataFrame:
    if start_date is None and end_date is None:
        return frame
    report_dates = (
        pd.to_datetime(frame[SliceColumn.EXCHANGE_TIME.value], utc=True)
        .dt.tz_convert('America/New_York')
        .dt.date
    )
    mask = pd.Series(True, index=frame.index)
    if start_date is not None:
        mask &= report_dates >= start_date
    if end_date is not None:
        mask &= report_dates <= end_date
    return frame.loc[mask].copy()


def load_thetadata_eod_cache(
    cache_root: str | Path,
    *,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
) -> OptionsDataDFs:
    """Load a date-filtered ThetaData cache as one research-ready OCA container.

    Only monthly Parquet partitions overlapping the inclusive report-date
    bounds are read.
    """
    report_start = _as_date(start_date, 'start_date') if start_date is not None else None
    report_end = _as_date(end_date, 'end_date') if end_date is not None else None
    if report_start is not None and report_end is not None and report_start > report_end:
        raise ValueError('start_date must not be after end_date')

    cache_root = Path(cache_root).expanduser().resolve()
    manifest_path = cache_root.joinpath('manifest.json')
    if not manifest_path.is_file():
        raise FileNotFoundError(f'missing ThetaData cache manifest: {manifest_path}')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    configuration = manifest.get('configuration', {})
    if configuration.get('cache_format') != CACHE_FORMAT:
        raise ValueError(f'unsupported ThetaData cache format at {cache_root}')

    option_files = _select_partitions(
        sorted(cache_root.joinpath('options').glob('*.parquet')), report_start, report_end
    )
    spot_files = _select_partitions(
        sorted(cache_root.joinpath('spot').glob('*.parquet')), report_start, report_end
    )
    if not option_files or not spot_files:
        raise ValueError(f'no ThetaData cache partitions at {cache_root} overlap the requested dates')

    chain_ts = _coerce_oca_options_frame(
        pd.concat((pd.read_parquet(path) for path in option_files), ignore_index=True)
    )
    chain_ts = _filter_report_dates(chain_ts, report_start, report_end)
    chain_ts = chain_ts.sort_values(
        [
            SliceColumn.EXCHANGE_TIME.value,
            SliceColumn.EXPIRY.value,
            SliceColumn.STRIKE.value,
            SliceColumn.OPTION_TYPE.value,
        ]
    ).drop_duplicates(
        [SliceColumn.EXCHANGE_TIME.value, SliceColumn.CONTRACT.value], keep='last'
    )
    spot_data = pd.concat((pd.read_parquet(path) for path in spot_files), ignore_index=True)
    spot_data[SliceColumn.EXCHANGE_TIME.value] = pd.to_datetime(
        spot_data[SliceColumn.EXCHANGE_TIME.value], utc=True
    )
    spot_data = _filter_report_dates(spot_data, report_start, report_end)
    spot_data['close'] = pd.to_numeric(spot_data['close'], errors='raise').astype('float64')
    spot_data = (
        spot_data.sort_values(SliceColumn.EXCHANGE_TIME.value)
        .drop_duplicates(SliceColumn.EXCHANGE_TIME.value, keep='last')
        .set_index(SliceColumn.EXCHANGE_TIME.value)
    )
    if chain_ts.empty or spot_data.empty:
        raise ValueError(f'no ThetaData EOD observations at {cache_root} match the requested dates')
    return OptionsDataDFs(
        chain_ts=chain_ts.reset_index(drop=True),
        spot_data=spot_data,
        ticker=str(configuration['ticker']),
    )
