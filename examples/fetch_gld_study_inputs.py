"""Acquire GLD EOD option/stock reports on a frozen research date calendar.

Repository-only OCA example. Raw American quotes are retained without parity
normalization or quality filtering. Existing files require matching fingerprints.
"""
import argparse
from enum import Enum
import hashlib
from importlib.metadata import version
import json
import logging
from pathlib import Path
import time

import numpy as np
import pandas as pd

from examples.fetch_hyg_quote_audit import validate_report


class Locals(Enum):
    """Available operation."""
    FETCH = 'fetch'


def digest(path):
    """Fingerprint an existing artifact."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(frame, day, asset):
    """Check identity and report cutoff without treating creation as quote age."""
    if asset == 'options':
        validate_report(frame, day, ticker='GLD')
        if (not frame.right.isin(['CALL', 'PUT']).all()
                or not (np.isfinite(frame.strike) & frame.strike.gt(0)).all()):
            raise ValueError('Invalid GLD contract identity')
        if not (pd.to_datetime(frame.expiration) >= pd.Timestamp(day)).all():
            raise ValueError('Expired GLD contract')
    elif asset == 'spot':
        if (len(frame) != 1 or not {'created', 'close'}.issubset(frame)
                or not (np.isfinite(frame.close) & frame.close.gt(0)).all()):
            raise ValueError('Invalid GLD close')
    else:
        raise ValueError('Unknown asset')
    if not frame.created.astype(str).str.contains(r'(?:Z|[+-]\d{2}:\d{2})$').all():
        raise ValueError('Missing explicit report timezone')
    stamps = pd.to_datetime(frame.created, utc=True, format='ISO8601')
    cutoff = pd.Timestamp(f'{day} 18:00:00', tz='America/New_York')
    if (not stamps.dt.tz_convert('America/New_York').dt.date.eq(cutoff.date()).all()
            or stamps.isna().any() or (stamps > cutoff).any()):
        raise ValueError('Report is not available by the same-day research cutoff')


def acquire(selection, output, client=None):
    """Fetch 460-DTE wildcard EOD options and same-day closes, with checkpoints."""
    frame = pd.read_csv(selection)
    dates = pd.to_datetime(frame.date)
    if dates.isna().any() or dates.duplicated().any() or not len(dates):
        raise ValueError('Expected a unique, nonempty frozen date calendar')
    config = {'ticker': 'GLD', 'dates': dates.dt.strftime('%Y-%m-%d').sort_values().tolist(),
        'max_dte': 460, 'source_sha256': digest(__file__), 'selection_sha256': digest(selection),
        'sdk': version('thetadata'), 'price_unit': 'USD/share',
        'clock': 'EOD reports by 18:00 ET; created is not last quote-update time'}
    output.mkdir(parents=True, exist_ok=True)
    design = output/'design.json'
    if design.exists() and json.loads(design.read_text()) != config:
        raise ValueError('Changed acquisition design; use a new directory')
    design.write_text(json.dumps(config, indent=2)+'\n')
    record_path = output/'manifest.json'
    record = json.loads(record_path.read_text()) if record_path.exists() else {'hashes': {}}
    records = []
    for day in config['dates']:
        counts = {}
        for asset in ('options', 'spot'):
            path = output/f'{asset}_{day}.csv'
            try:
                if path.exists():
                    if record['hashes'].get(path.name) != digest(path):
                        raise ValueError('Changed or unrecorded raw report')
                    report = pd.read_csv(path)
                else:
                    if client is None:
                        logging.disable(logging.CRITICAL)
                        from thetadata import ThetaClient
                        client = ThetaClient(dataframe_type='pandas')
                    kwargs = dict(symbol='GLD', start_date=pd.Timestamp(day).date(),
                                  end_date=pd.Timestamp(day).date())
                    try:
                        report = (client.option_history_eod(**kwargs, expiration='*', max_dte=460)
                                  if asset == 'options' else client.stock_history_eod(**kwargs))
                    finally:
                        time.sleep(2.1)
                    validate(report, day, asset)
                    report.to_csv(path, index=False)
                    record['hashes'][path.name] = digest(path)
                    record_path.write_text(json.dumps(record, indent=2)+'\n')
                validate(report, day, asset)
                counts[asset+'_rows'] = len(report)
            except Exception as exc:
                code = exc.code().name if callable(getattr(exc, 'code', None)) else None
                records.append({'date': day, 'asset': asset, 'status': 'failed',
                                'error_type': type(exc).__name__, 'provider_status': code})
                pd.DataFrame(records).to_csv(output/'availability.csv', index=False)
                raise RuntimeError(f'GLD {day} {asset}: {type(exc).__name__} {code}') from None
        records.append({'date': day, 'status': 'acquired', **counts})
        pd.DataFrame(records).to_csv(output/'availability.csv', index=False)
        print(day, counts, flush=True)


def run_local(local=Locals.FETCH):
    """Run with the external OCA interpreter and securely configured credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if local == Locals.FETCH:
        acquire(args.selection, args.output)


if __name__ == '__main__':
    run_local()
