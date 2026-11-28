"""Build a private, versioned ETF option and consolidated stock cutoff dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from enum import Enum
from functools import partial
from importlib.metadata import version
from pathlib import Path
from threading import Lock
from time import sleep
from uuid import uuid4

import pandas as pd
from option_chain_analytics.data.thetadata_cache import _write_json_atomic
from option_chain_analytics.data.thetadata_sync import (
    ZONE,
    check_stock,
    normalize,
    schedule,
    timestamps,
)

TICKERS = ('HYG', 'TLT', 'GLD')
VENUE = 'utp_cta'
ENDPOINTS = {
    'calendar_year': 'GetCalendarYear',
    'stock_at_time_quote': 'GetStockAtTimeQuote',
    'option_at_time_quote': 'GetOptionAtTimeQuote',
    'option_history_greeks_first_order': 'GetOptionHistoryGreeksFirstOrder',
    'stock_history_quote': 'GetStockHistoryQuote',
}
RETRYABLE = {'UNAUTHENTICATED', 'UNAVAILABLE', 'DEADLINE_EXCEEDED', 'INTERNAL', 'RESOURCE_EXHAUSTED'}
SPLITTABLE = ('INVALID_ARGUMENT', 'INTERNAL', 'DEADLINE_EXCEEDED')


class Locals(Enum):
    BUILD = 'build'


class RequestFailed(RuntimeError):
    """Sanitized provider error, safe to include in manifests."""


class AllExpiries(str):
    """Adapt the SDK's date formatter to the documented one-day wildcard."""

    def strftime(self, _):
        return str(self)


class Service:
    def __init__(self):
        self.lock = Lock()
        self.client = self.connect()

    @staticmethod
    def connect():
        logging.disable(logging.CRITICAL)
        from thetadata import ThetaClient

        client = ThetaClient(dataframe_type='pandas')
        if min(client.stock_subscription, client.options_subscription) < 2:
            raise ValueError('The job requires both ThetaData Standard subscriptions')
        for name in (*ENDPOINTS.values(), 'GetOptionListContracts'):
            setattr(client.stub, name, partial(getattr(client.stub, name), timeout=45))
        return client

    def request(self, endpoint: str, kwargs: dict) -> pd.DataFrame:
        from grpc import RpcError
        from thetadata.errors import NoDataFoundError

        for attempt in range(3):
            client = self.client
            try:
                return getattr(client, endpoint)(**kwargs)
            except NoDataFoundError:
                return pd.DataFrame()
            except (RpcError, OSError, RuntimeError, ValueError, TypeError) as exc:
                code = exc.code().name if callable(getattr(exc, 'code', None)) else type(exc).__name__
                if code not in RETRYABLE or attempt == 2:
                    raise RequestFailed(f'{endpoint} returned {code}') from None
                if code == 'UNAUTHENTICATED':
                    with self.lock:
                        if self.client is client:
                            self.client = self.connect()
                sleep(2 ** attempt)
        raise AssertionError('Request retries exhausted without an outcome')


def digest(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


RUNNER_SHA256 = digest(Path(__file__))


def move(source: Path, destination: Path, *, replace: bool = False):
    operation = source.replace if replace else source.rename
    for attempt in range(4):
        try:
            operation(destination)
            return
        except PermissionError:
            if attempt == 3:
                raise
            sleep(attempt + 1)


def atomic_parquet(frame: pd.DataFrame, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f'.{target.name}.{uuid4().hex}.tmp')
    frame.to_parquet(temp, index=False, compression='zstd')
    move(temp, target, replace=True)


def saved_request(service: Service, folder: Path, endpoint: str, **kwargs) -> pd.DataFrame:
    metadata = folder / 'request.json'
    path = folder / 'data.parquet'
    params = json.loads(json.dumps(kwargs, default=str))
    if metadata.exists():
        record = json.loads(metadata.read_bytes())
        if record['parameters'] != params or record['endpoint'] != endpoint or digest(path) != record['sha256']:
            raise ValueError(f'Changed or corrupt raw request at {folder}')
        return pd.read_parquet(path)
    if folder.exists():
        raise ValueError(f'Incomplete raw request directory at {folder}')
    data = service.request(endpoint, kwargs)
    raw = data.copy()
    for col in ('timestamp', 'underlying_timestamp'):
        if col in raw:
            raw[col] = raw[col].astype('string')
    folder.parent.mkdir(parents=True, exist_ok=True)
    staged = folder.with_name(f'.incoming-{uuid4().hex}')
    staged.mkdir()
    raw.to_parquet(staged / path.name, index=False, compression='zstd')
    _write_json_atomic(staged / metadata.name, {
        'endpoint': endpoint, 'parameters': params, 'rows': len(raw), 'sha256': digest(staged / path.name),
        'status': 'available' if len(raw) else 'no_data',
        'acquired_utc': pd.Timestamp.now(tz='UTC').isoformat(), 'sdk_version': version('thetadata'),
        'timestamp_representation': 'SDK timestamp rendered as a string; original offset retained',
    })
    try:
        move(staged, folder)
    except FileExistsError:
        shutil.rmtree(staged)
        return saved_request(service, folder, endpoint, **kwargs)
    return raw


def by_day(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {}
    stamp = timestamps(frame['timestamp'])
    return dict(tuple(frame.groupby(stamp.dt.tz_convert(ZONE).dt.strftime('%Y-%m-%d'))))


def clock_groups(block: pd.DataFrame):
    return block.groupby('time_of_day', sort=True)


def fetch_stock(service: Service, root: Path, ticker: str, month: str, block: pd.DataFrame) -> dict:
    results = {}
    for clock, group in clock_groups(block):
        lo, hi = map(date.fromisoformat, (group['date'].min(), group['date'].max()))
        quotes = saved_request(service, root / 'raw' / ticker / month / f'stock-{clock[:2]}{clock[3:5]}',
                               'stock_at_time_quote', symbol=ticker, start_date=lo, end_date=hi,
                               time_of_day=clock, venue=VENUE)
        allowed = set(group['date'])
        results.update({day: data for day, data in by_day(quotes).items() if day in allowed})
    return results


def listed_expiries(frame: pd.DataFrame, day: date, limit: int) -> list[date]:
    if frame.empty or 'expiration' not in frame:
        return []
    expiry = pd.to_datetime(frame['expiration'], errors='coerce')
    return sorted(set(expiry.loc[(expiry - pd.Timestamp(day)).dt.days.between(0, limit)].dt.date))


def recover_expiries(service: Service, folder: Path, endpoint: str, params: dict,
                     expiries: list[date], contracts: pd.DataFrame | None = None) -> tuple[pd.DataFrame, list]:
    frames, errors = [], []
    for expiry in expiries:
        try:
            value = saved_request(service, folder / str(expiry), endpoint, **params, expiration=expiry)
            if not value.empty:
                frames.append(value)
        except RequestFailed as exc:
            if contracts is None or not str(exc).endswith(SPLITTABLE):
                errors.append({'expiry': str(expiry), 'failure': str(exc)})
                continue
            listed = contracts.loc[pd.to_datetime(contracts['expiration']).eq(pd.Timestamp(expiry))]
            for right, options in listed.groupby(listed['right'].str.lower()):
                right_params = {**params, 'expiration': expiry, 'right': right}
                try:
                    part = saved_request(service, folder / f'{expiry}-{right}', endpoint, **right_params)
                except RequestFailed as right_error:
                    if not str(right_error).endswith(SPLITTABLE):
                        errors.append({'expiry': str(expiry), 'right': right, 'failure': str(right_error)})
                        continue
                    for strike in sorted(options['strike'].unique()):
                        token = f'{strike:.3f}'.rstrip('0').rstrip('.')
                        try:
                            one = saved_request(service, folder / f'{expiry}-{right}-{token}', endpoint,
                                                **right_params, strike=token)
                            if not one.empty:
                                frames.append(one)
                        except RequestFailed as strike_error:
                            errors.append({'expiry': str(expiry), 'right': right, 'strike': float(strike),
                                           'failure': str(strike_error)})
                else:
                    if not part.empty:
                        frames.append(part)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), errors


def option_snapshot(service: Service, root: Path, ticker: str, day: date, clock: str, limit: int,
                    repair_contracts: bool = False,
                    request_strike_range: int | None = None,
                    ) -> tuple[pd.DataFrame, list]:
    endpoint = 'option_at_time_quote'
    params = {'symbol': ticker, 'start_date': day, 'end_date': day, 'time_of_day': clock, 'max_dte': limit}
    if request_strike_range is not None:
        params.update(strike_range=request_strike_range, time_of_day=f'{clock}.000')
    primary = root / f'options-{day}'
    fallback = root / f'option-contracts-{day}'
    try:
        if not fallback.exists():
            frame = saved_request(service, primary, endpoint, **params, expiration='*')
            if not frame.empty or not repair_contracts:
                return frame, []
    except RequestFailed as exc:
        if not str(exc).endswith(SPLITTABLE):
            return pd.DataFrame(), [{'failure': str(exc)}]
    try:
        contracts = saved_request(service, fallback, 'option_list_contracts', request_type='quote',
                                  date=day, symbol=ticker, max_dte=limit)
    except RequestFailed as exc:
        return pd.DataFrame(), [{'failure': str(exc)}]
    expiries = listed_expiries(contracts, day, limit)
    if not expiries:
        errors = [] if primary.exists() else [{'failure': 'Option snapshot failed and no fallback expiries returned'}]
        return pd.DataFrame(), errors
    return recover_expiries(service, root / f'option-fallback-{day}', endpoint, params, expiries,
                            contracts if repair_contracts else None)


def greek_snapshot(service: Service, root: Path, ticker: str, day: date, clock: str,
                   options: pd.DataFrame, limit: int, repair_contracts: bool = False,
                   request_strike_range: int | None = None) -> tuple[pd.DataFrame, list]:
    expiries = listed_expiries(options, day, limit)
    if not expiries:
        return pd.DataFrame(), []
    endpoint = 'option_history_greeks_first_order'
    params = {'symbol': ticker, 'date': day, 'interval': '1m', 'start_time': clock, 'end_time': clock}
    if request_strike_range is not None:
        params['strike_range'] = request_strike_range
    try:
        frame = saved_request(service, root / f'greeks-all-{day}', endpoint, **params, expiration=AllExpiries('*'))
        return frame, []
    except RequestFailed as exc:
        if not str(exc).endswith(SPLITTABLE):
            return pd.DataFrame(), [{'failure': str(exc)}]
    return recover_expiries(service, root / f'greeks-fallback-{day}', endpoint, params, expiries,
                            options if repair_contracts else None)


def reference_stock(service: Service, output: Path, ticker: str, row, stocks: pd.DataFrame,
                    greeks: pd.DataFrame) -> pd.DataFrame:
    if greeks.empty or 'underlying_timestamp' not in greeks:
        return stocks
    refs = timestamps(greeks['underlying_timestamp'])
    start = row.snapshot_timestamp - pd.Timedelta(minutes=5)
    earlier = refs.loc[refs.ge(start) & refs.lt(row.snapshot_timestamp)]
    if earlier.empty:
        return stocks
    day = date.fromisoformat(row.date)
    start_time = earlier.min().floor('s').tz_convert(ZONE).strftime('%H:%M:%S')
    history = saved_request(service, output / f'reference-stock-{day}', 'stock_history_quote',
                            symbol=ticker, venue=VENUE, date=day, interval='1s',
                            start_time=start_time, end_time=row.time_of_day)
    return pd.concat([history, stocks], ignore_index=True)


def eod_comparison(status: dict, panel: pd.DataFrame, end: pd.Timestamp, old: dict) -> dict:
    quotes = old.get(end.strftime('%Y-%m-%d'))
    if quotes is None or not status.get('stock_valid', False):
        return {}
    spot, eod = quotes
    if not len(panel):
        return {'prior_eod_close': spot, 'cutoff_mid_minus_eod_close': status['stock_mid'] - spot}
    keys = ['expiration', 'strike', 'right']
    cutoff_quotes = panel.loc[panel['eligible'], [*keys, 'bid', 'ask']]
    both = cutoff_quotes.merge(eod, on=keys, how='inner', validate='one_to_one')
    difference = ((both['bid'] + both['ask']) - (both['bid_price'] + both['ask_price'])) * .5
    return {'prior_eod_close': spot, 'cutoff_mid_minus_eod_close': status['stock_mid'] - spot,
            'matched_prior_eod_contracts': len(both),
            'median_abs_option_mid_change': float(difference.abs().median())}


def previous_eod(root: Path | None, ticker: str, month: str) -> dict:
    if root is None:
        return {}
    path = (root / 'thetadata_options' / ticker.lower() if ticker in ('GLD', 'SPY')
            else root / 'thetadata_options_backtest' / f'{ticker.lower()}_400d')
    opt = path / 'options' / f'{month}.parquet'
    stock = path / 'spot' / f'{month}.parquet'
    if not opt.is_file() or not stock.is_file():
        return {}
    s = pd.read_parquet(stock, columns=['exchange_time', 'close'])
    q = pd.read_parquet(opt, columns=['exchange_time', 'expiry', 'strike', 'optiontype', 'bid_price', 'ask_price'])
    dates = q['exchange_time'].dt.tz_convert(ZONE).dt.strftime('%Y-%m-%d')
    q['expiration'] = q['expiry'].dt.tz_convert(ZONE).dt.tz_localize(None).dt.normalize()
    q['right'] = q['optiontype'].replace({'C': 'CALL', 'P': 'PUT'})
    s.index = s['exchange_time'].dt.tz_convert(ZONE).dt.strftime('%Y-%m-%d')
    keys = ['expiration', 'strike', 'right']
    return {day: (float(s.at[day, 'close']), rows.sort_values('exchange_time').drop_duplicates(keys, keep='last'))
            for day, rows in q.groupby(dates) if day in s.index}


def month_job(service: Service, root: Path, ticker: str, month: str, block: pd.DataFrame,
              stock: dict, args, first_stock: str) -> dict:
    target = root / 'panel' / ticker / month
    manifest = target / 'manifest.json'
    if manifest.is_file():
        current = json.loads(manifest.read_bytes())
        if any(digest(target / name) != sha for name, sha in current['sha256'].items()):
            raise ValueError(f'Corrupt panel partition at {target}')
        if not current['failures']:
            past_schedule = pd.read_parquet(target / 'sessions.parquet', columns=[
                'date', 'stock_quote_timestamp', 'stock_valid', 'options_available',
            ])
            retry_empty = (args.repair_contracts and not current.get('empty_snapshot_retry')
                           and (past_schedule['stock_valid'] & ~past_schedule['options_available']).any())
            if current.get('stock_alignment') == 'same_session_asof' and not retry_empty:
                return current
            old_times = past_schedule.set_index('date')['stock_quote_timestamp'].to_dict()
            has_earlier_stock = any(
                pd.notna(stamp) and (pd.isna(old_times[day]) or stamp != old_times[day])
                for day, quotes in stock.items() if day in old_times
                for stamp in [timestamps(quotes['timestamp']).max()]
            )
            if not has_earlier_stock and not retry_empty:
                return current
    options, greeks, failures = {}, {}, []
    raw_root = root / 'raw' / ticker / month
    for row in block.itertuples(index=False):
        if row.date < first_stock and not args.sessions:
            continue
        day = date.fromisoformat(row.date)
        option, option_errors = option_snapshot(service, raw_root, ticker, day, row.time_of_day, args.max_dte,
                                                args.repair_contracts, args.request_strike_range)
        greek, greek_errors = greek_snapshot(service, raw_root, ticker, day, row.time_of_day, option, args.max_dte,
                                             args.repair_contracts, args.request_strike_range)
        options[row.date], greeks[row.date] = option, greek
        failures.extend({'date': row.date, **item} for item in [*option_errors, *greek_errors])
    old = previous_eod(args.eod_root, ticker, month)
    statuses, frames = [], []
    empty = pd.DataFrame()
    for row in block.itertuples(index=False):
        spot = stock.get(row.date, empty)
        option = options.get(row.date, empty)
        greek = greeks.get(row.date, empty)
        try:
            samples = reference_stock(service, root / 'raw' / ticker / month, ticker, row, spot, greek)
        except RequestFailed as exc:
            samples = spot
            failures.append({'date': row.date, 'failure': str(exc)})
        panel, status = normalize(ticker, row.snapshot_timestamp, spot, option, greek, max_dte=args.max_dte,
                                  strike_range=args.strike_range, option_max_age=args.option_max_age,
                                  stock_samples=samples)
        status['date'] = row.date
        status['early_close'] = row.early_close
        status['options_requested'] = row.date >= first_stock or bool(args.sessions)
        if not status['options_requested']:
            status['quality'] = 'outside_available_stock_history'
        if not panel.empty:
            frames.append(panel)
        status.update(eod_comparison(status, panel, pd.Timestamp(row.date), old))
        statuses.append(status)
    panel = pd.concat(frames, ignore_index=True) if frames else empty
    tables = {'quotes.parquet': panel, 'sessions.parquet': pd.DataFrame(statuses)}
    incoming = root / '.pending' / f'{ticker}-{month}-{uuid4().hex}'
    incoming.mkdir(parents=True)
    for name, frame in tables.items():
        atomic_parquet(frame, incoming / name)
    current = {
        'ticker': ticker, 'month': month, 'rows': len(panel), 'sessions': len(statuses), 'failures': failures,
        'sha256': {name: digest(incoming / name) for name in tables},
        'runner_sha256': RUNNER_SHA256,
        'stock_alignment': 'same_session_asof',
        'empty_snapshot_retry': args.repair_contracts,
    }
    _write_json_atomic(incoming / 'manifest.json', current)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = root / '.replaced' / f'{ticker}-{month}-{uuid4().hex}'
        backup.parent.mkdir(parents=True, exist_ok=True)
        move(target, backup)
        try:
            move(incoming, target)
        except OSError:
            move(backup, target)
            raise
    else:
        move(incoming, target)
    print(f'{ticker} {month} {len(panel)} rows, {len(failures)} request failures', flush=True)
    return current


def percentile(series: pd.Series) -> dict:
    data = pd.to_numeric(series, errors='coerce').dropna()
    return {f'p{v}': float(data.quantile(v / 100)) for v in (50, 90, 95, 99)} if len(data) else {}


def coverage(root: Path, ticker: str, output: list[dict]) -> dict:
    import pyarrow.parquet as pq

    dates, ages, cutoff_gaps, reference_gaps = [], [], [], []
    eligible_rows = n60 = n300 = greek_matches = 0
    quote_metrics = ('eligible', 'option_quote_older_60s', 'option_quote_older_300s', 'provider_greeks_matched',
                     'option_quote_age_seconds', 'provider_underlying_minus_cutoff_mid',
                     'provider_underlying_minus_reference_mid')
    for month in sorted(item['month'] for item in output if item['ticker'] == ticker):
        path = root / 'panel' / ticker / month
        dates.append(pd.read_parquet(path / 'sessions.parquet'))
        quotes_path = path / 'quotes.parquet'
        parquet = pq.ParquetFile(quotes_path)
        if not parquet.metadata.num_rows:
            continue
        fields = [name for name in quote_metrics if name in parquet.schema.names]
        quotes = pd.read_parquet(quotes_path, columns=fields)
        select = quotes.loc[quotes['eligible']]
        eligible_rows += len(select)
        n60 += int(select['option_quote_older_60s'].sum())
        n300 += int(select['option_quote_older_300s'].sum())
        greek_matches += int(select['provider_greeks_matched'].sum())
        ages.append(select['option_quote_age_seconds'])
        for field, series in [('provider_underlying_minus_cutoff_mid', cutoff_gaps),
                              ('provider_underlying_minus_reference_mid', reference_gaps)]:
            if field in select:
                series.append(select[field].abs())
    sessions = pd.concat(dates, ignore_index=True).sort_values('date')
    outcomes = [item for partition in output if partition['ticker'] == ticker for item in partition['failures']]
    diagnostic_endpoints = ('option_history_greeks_', 'stock_history_quote')
    quote_errors = {item['date'] for item in outcomes
                    if 'date' in item and not item['failure'].startswith(diagnostic_endpoints)}
    diagnostic_errors = {item['date'] for item in outcomes
                         if 'date' in item and item['failure'].startswith(diagnostic_endpoints)}
    sessions['partial_quote_acquisition'] = sessions['date'].isin(quote_errors)
    sessions['diagnostic_request_failure'] = sessions['date'].isin(diagnostic_errors)
    sessions['complete'] = sessions['aligned'] & ~sessions['partial_quote_acquisition']
    atomic_parquet(sessions, root / f'{ticker}_sessions.parquet')

    def interval(mask):
        values = sessions.loc[mask, 'date']
        return [values.min(), values.max()] if len(values) else []

    return {
        'requested_range': interval(sessions['date'].notna()),
        'option_available_range': interval(sessions['options_available']),
        'stock_available_range': interval(sessions['stock_valid']),
        'aligned_range': interval(sessions['aligned']),
        'complete_range': interval(sessions['complete']),
        'requested_sessions': len(sessions), 'aligned_sessions': int(sessions['aligned'].sum()),
        'complete_sessions': int(sessions['complete'].sum()),
        'gap_counts': sessions.loc[~sessions['aligned'], 'quality'].value_counts().to_dict(),
        'partial_quote_sessions': int(sessions.loc[sessions['aligned'], 'partial_quote_acquisition'].sum()),
        'partial_quote_dates': sorted(quote_errors), 'diagnostic_failure_dates': sorted(diagnostic_errors),
        'eligible_option_rows': eligible_rows, 'matched_provider_greeks': greek_matches,
        'provider_underlying_reference_matches': int(sum(series.count() for series in reference_gaps)),
        'stock_event_age_seconds': percentile(sessions['stock_quote_age_seconds']),
        'stock_sessions_with_event_age': int(sessions['stock_quote_age_seconds'].notna().sum()),
        'stock_sample_lag_seconds': percentile(sessions['stock_sample_lag_seconds']),
        'option_age_seconds': percentile(pd.concat(ages)) if ages else {},
        'eligible_options_over_60_seconds': n60, 'eligible_options_over_300_seconds': n300,
        'provider_underlying_abs_minus_cutoff_dollars': percentile(pd.concat(cutoff_gaps)) if cutoff_gaps else {},
        'provider_underlying_abs_minus_matched_stock_dollars': (
            percentile(pd.concat(reference_gaps)) if reference_gaps else {}
        ),
        'cutoff_mid_abs_minus_eod_close_dollars': percentile(sessions.get(
            'cutoff_mid_minus_eod_close', pd.Series(dtype=float),
        ).abs()),
        'eod_comparison_sessions': int(sessions.get('prior_eod_close', pd.Series(dtype=float)).count()),
        'mean_matched_eod_contracts': (
            float(sessions['matched_prior_eod_contracts'].fillna(0).sum())
            / max(1, int(sessions['matched_prior_eod_contracts'].count()))
            if 'matched_prior_eod_contracts' in sessions else 0.
        ),
        'daily_median_option_mid_abs_change_from_eod_dollars': percentile(sessions.get(
            'median_abs_option_mid_change', pd.Series(dtype=float),
        )),
    }


def run_local(local=Locals.BUILD):
    if local != Locals.BUILD:
        raise ValueError(local)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tickers', nargs='+', choices=(*TICKERS, 'SPY'), default=list(TICKERS))
    for field in ('start', 'end'):
        parser.add_argument(f'--{field}', type=date.fromisoformat, required=True)
    parser.add_argument('--sessions', nargs='+', help='Explicit validation sessions within the declared range')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--eod-root', type=Path)
    parser.add_argument('--max-dte', type=int, default=460)
    parser.add_argument('--strike-range', type=int)
    parser.add_argument('--request-strike-range', type=int,
                        help='Limit the provider requests to this many strikes per side before OCA validation')
    parser.add_argument('--option-max-age', type=float)
    parser.add_argument('--repair-contracts', action='store_true',
                        help='Recover malformed expiry responses by option right and strike')
    parser.add_argument('--workers', type=int, choices=(1, 2, 3, 4), default=4)
    args = parser.parse_args()
    if args.start > args.end or args.max_dte <= 0 or (args.strike_range is not None and args.strike_range < 1):
        parser.error('Invalid date or contract limits')
    if args.request_strike_range is not None and args.request_strike_range < 1:
        parser.error('Provider strike range must be positive')
    root = args.output
    root.mkdir(parents=True, exist_ok=True)
    service = Service()
    parts = [saved_request(service, root / 'calendar' / str(year), 'calendar_year', year=str(year))
             for year in range(args.start.year, args.end.year + 1)]
    cal = schedule(pd.concat(parts, ignore_index=True), args.start, args.end, pd.Timestamp.now(tz='UTC'))
    if args.sessions:
        cal = cal.loc[cal['date'].isin(args.sessions)]
        if set(args.sessions) != set(cal['date']):
            raise ValueError('A pilot date is outside the completed-session schedule')
    if cal.empty:
        raise ValueError('No completed sessions in the requested range')
    for name, day, clock in [('2024', '2024-11-29', '12:55:00'), ('2026', '2026-11-27', '12:55:00')]:
        if (args.start <= date.fromisoformat(day) <= args.end and day in set(cal['date'])
                and not cal.loc[cal['date'].eq(day), 'time_of_day'].eq(clock).all()):
            raise ValueError(f'Unexpected NYSE early close for {name}')
    date_list = cal['date'].tolist()
    design = {
        'version': '1', 'tickers': sorted(set(args.tickers)), 'start': str(args.start), 'end': str(args.end),
        'sessions': date_list, 'calendar': 'ThetaData US exchange exceptions with NYSE early-close checks',
        'cutoff': 'five minutes prior to regular stock-market close', 'timezone': ZONE, 'stock_venue': VENUE,
        'sdk': version('thetadata'), 'pandas': version('pandas'), 'pyarrow': version('pyarrow'),
        'oca': version('option-chain-analytics'), 'max_dte': args.max_dte, 'strike_range': args.strike_range,
        'option_max_age': args.option_max_age, 'greeks_interval': '1m exact cutoff grid',
        'comparison_stock_interval': '1s backward, within five minutes of cutoff', 'eod_root': str(args.eod_root),
        'expiry_and_strike_policy': 'provider DTE hint; local limits; no provider strike filter',
        'endpoint_names': sorted(ENDPOINTS),
    }
    if args.request_strike_range is not None:
        design['request_strike_range'] = args.request_strike_range
        design['expiry_and_strike_policy'] = 'provider DTE and strike hints; independent local limits'
    frozen = root / 'design.json'
    if frozen.is_file() and design != json.loads(frozen.read_bytes()):
        raise ValueError('Changed acquisition design; choose a new versioned output folder')
    _write_json_atomic(frozen, design)
    atomic_parquet(cal, root / 'schedule.parquet')
    months = list(cal.groupby(cal['date'].str[:7], sort=True))
    blocks = [(ticker, month, block) for month, block in months for ticker in design['tickers']]
    call = partial(fetch_stock, service, root)
    stock_results = {}
    stock_failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        data = [(task, pool.submit(call, *task)) for task in blocks]
        for (ticker, month, _), promised in data:
            try:
                stock_results[(ticker, month)] = promised.result()
            except RequestFailed as exc:
                stock_failures.append({'ticker': ticker, 'month': month, 'failure': str(exc)})
    starts = {}
    cutoffs = cal.set_index('date')['snapshot_timestamp'].to_dict()
    for ticker in design['tickers']:
        found = {day: quotes for (symbol, _), stock in stock_results.items() if symbol == ticker
                 for day, quotes in stock.items()}
        starts[ticker] = next((day for day in sorted(found) if check_stock(found[day], cutoffs[day])['stock_valid']),
                              '9999-12-31')
        print(ticker, 'first independent stock report', starts[ticker], flush=True)
    if stock_failures and not args.sessions:
        _write_json_atomic(root / 'stock_failures.json', {'failures': stock_failures})
        raise RequestFailed('One or more historical stock availability requests exhausted retries')
    last_month = months[-1][0]
    blocks.sort(key=lambda task: task[1] != last_month)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = [pool.submit(month_job, service, root, ticker, month, block,
                               stock_results.get((ticker, month), {}), args, starts[ticker])
                   for ticker, month, block in blocks]
        results = [task.result() for task in pending]
    report = {ticker: coverage(root, ticker, results) for ticker in design['tickers']}
    errors = stock_failures + [{'ticker': r['ticker'], 'month': r['month'], **item}
                               for r in results for item in r['failures']]
    _write_json_atomic(root / 'coverage.json', {'tickers': report, 'request_failures': errors,
                                               'partitions': results, 'design_sha256': digest(frozen),
                                               'schedule_sha256': digest(root / 'schedule.parquet')})
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    run_local(local=Locals.BUILD)
