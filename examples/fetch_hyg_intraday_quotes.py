"""Fetch private HYG at-time NBBO snapshots on an explicit New York schedule.

Repository-only acquisition example. Prices are USD per underlying share.
The schedule CSV must contain unique dates and minute-boundary ``time_of_day``;
the caller owns exchange-calendar selection, including half days. The request
asks for expiries through 460 days; raw extra expiries are retained because the
provider may ignore this bound. Downstream studies must enforce it locally.
"""
import argparse
from datetime import datetime, timezone
from enum import Enum
import hashlib
from importlib.metadata import version
import json
import logging
from pathlib import Path
import time

import numpy as np
import pandas as pd


class Locals(Enum):
    """Available acquisition operation."""
    FETCH = 'fetch'


def digest(path):
    """Return the exact file fingerprint."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_schedule(path):
    """Reject duplicate dates and require an explicit minute boundary."""
    frame = pd.read_csv(path, dtype=str)
    if frame.empty or not {'date', 'time_of_day'}.issubset(frame):
        raise ValueError('Expected nonempty date/time_of_day schedule')
    dates = pd.to_datetime(frame.date, format='%Y-%m-%d', errors='raise')
    if dates.duplicated().any() or not dates.dt.strftime('%Y-%m-%d').eq(frame.date).all():
        raise ValueError('Duplicate or noncanonical schedule dates')
    if not frame.time_of_day.str.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d:00').all():
        raise ValueError('Use HH:MM:00 minute boundaries')
    return frame.sort_values('date')[['date', 'time_of_day']].to_dict('records')


def validate_snapshot(frame, day, clock, asset):
    """Verify contract identity and that every quote precedes the requested cutoff.

    Quote age and bid/ask quality are downstream diagnostics. Raw zero bids,
    crossed markets and non-firm conditions remain in the saved vendor data.
    """
    required = {'timestamp', 'bid', 'ask', 'bid_size', 'ask_size',
                'bid_condition', 'ask_condition'}
    if asset == 'options':
        required |= {'symbol', 'expiration', 'strike', 'right'}
    elif asset != 'stock':
        raise ValueError('Unknown asset')
    if frame.empty or not required.issubset(frame):
        raise ValueError('Empty or incomplete quote snapshot')
    if not frame.timestamp.astype(str).str.contains(r'(?:Z|[+-]\d{2}:\d{2})$').all():
        raise ValueError('Quote timestamp lacks an explicit timezone')
    stamps = pd.to_datetime(frame.timestamp, utc=True, errors='raise', format='ISO8601')
    cutoff = pd.Timestamp(f'{day} {clock}', tz='America/New_York')
    if stamps.isna().any() or (stamps > cutoff).any():
        raise ValueError('Missing or future quote timestamp')
    if not stamps.dt.tz_convert('America/New_York').dt.date.eq(cutoff.date()).all():
        raise ValueError('Wrong New York quote date')
    if asset == 'options':
        if not frame.symbol.eq('HYG').all() or not frame.right.isin(['CALL', 'PUT']).all():
            raise ValueError('Unexpected option root or right')
        if frame.duplicated(['expiration', 'strike', 'right']).any():
            raise ValueError('Duplicate option identity')
        if not (np.isfinite(frame.strike) & frame.strike.gt(0)).all():
            raise ValueError('Invalid strike')
        days = (pd.to_datetime(frame.expiration) - pd.Timestamp(day)).dt.days
        if not days.ge(0).all():
            raise ValueError('Expired option in at-time snapshot')
    elif len(frame) != 1:
        raise ValueError('Expected exactly one underlying quote')
    return (cutoff - stamps).dt.total_seconds()


def acquire(selection, output, asset='options', client=None, pause=2.1):
    """Fetch or verify frozen raw files; fail closed on changed resumable inputs."""
    schedule = read_schedule(selection)
    output.mkdir(parents=True, exist_ok=True)
    config = {'ticker': 'HYG', 'asset': asset, 'schedule': schedule,
              'max_dte': 460, 'timezone': 'America/New_York',
              'price_unit': 'USD per underlying share', 'stock_venue': 'utp_cta',
              'selection_sha256': digest(selection), 'source_sha256': digest(__file__),
              'sdk_version': version('thetadata') if client is None else None,
              'max_dte_policy': 'request hint only; retain raw and enforce locally downstream',
              'quality_filter': 'none; identity and as-of timestamp validation only'}
    design = output / 'design.json'
    if design.exists() and json.loads(design.read_text()) != config:
        raise ValueError('Changed acquisition design; use a new directory')
    if not design.exists():
        design.write_text(json.dumps(config, indent=2) + '\n')
    manifest_path = output / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'hashes': {}}
    records = []
    for row in schedule:
        day, clock = row['date'], row['time_of_day']
        path = output / f'{asset}_{day}.csv'
        try:
            if path.exists():
                if manifest['hashes'].get(path.name) != digest(path):
                    raise ValueError('Unrecorded or changed cached snapshot')
                frame = pd.read_csv(path)
            else:
                if client is None:
                    logging.disable(logging.CRITICAL)  # SDK INFO can contain session tokens.
                    from thetadata import ThetaClient
                    client = ThetaClient(dataframe_type='pandas')
                kwargs = dict(symbol='HYG', start_date=pd.Timestamp(day).date(),
                              end_date=pd.Timestamp(day).date(), time_of_day=clock)
                try:
                    if asset == 'options':
                        frame = client.option_at_time_quote(**kwargs, expiration='*', max_dte=460)
                    else:
                        frame = client.stock_at_time_quote(**kwargs, venue='utp_cta')
                finally:
                    time.sleep(pause)
                # Preserve even rejected raw responses for investigation, never as acquired.
                try:
                    validate_snapshot(frame, day, clock, asset)
                except ValueError:
                    frame.to_csv(output / f'rejected_{asset}_{day}.csv', index=False)
                    raise
                temporary = path.with_suffix('.csv.partial')
                frame.to_csv(temporary, index=False)
                temporary.replace(path)
                manifest['hashes'][path.name] = digest(path)
                manifest['recorded_utc'] = datetime.now(timezone.utc).isoformat()
                manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
            ages = validate_snapshot(frame, day, clock, asset)
            records.append({**row, 'status': 'acquired', 'rows': len(frame),
                            'max_quote_age_seconds': float(ages.max()),
                            'quotes_older_than_60s': int(ages.gt(60).sum())})
        except Exception as exc:
            code = exc.code().name if callable(getattr(exc, 'code', None)) else None
            records.append({**row, 'status': 'failed', 'error_type': type(exc).__name__,
                            'provider_status': code,
                            'validation_error': str(exc) if isinstance(exc, ValueError) else None})
            pd.DataFrame(records).to_csv(output / 'availability.csv', index=False)
            raise RuntimeError(f'HYG {day} acquisition failed: {type(exc).__name__} {code}') from None
        pd.DataFrame(records).to_csv(output / 'availability.csv', index=False)
        print(day, clock, 'rows', len(frame), flush=True)


def run_local(local=Locals.FETCH):
    """Fetch the declared schedule using the optional ThetaData SDK."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--asset', choices=['options', 'stock'], default='options')
    args = parser.parse_args()
    if local == Locals.FETCH:
        acquire(args.selection, args.output, args.asset)


if __name__ == '__main__':
    run_local(local=Locals.FETCH)
