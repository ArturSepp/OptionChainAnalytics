"""Acquire dated HYG EOD reports for an OCA quote-quality comparison.

Repository-only private-data example. Preserve raw quote timestamps and sizes;
do not infer American-option forwards from parity at acquisition time.
"""
import argparse
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
from pathlib import Path
import time

import pandas as pd


class Locals(Enum):
    """Available acquisition operation."""
    FETCH = 'fetch'


def validate_report(frame, value_date, ticker='HYG'):
    """Separate provider availability from subsequent quote-quality admission."""
    required={'symbol','expiration','strike','right','created','bid','ask','bid_size','ask_size'}
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError('Empty or incomplete option EOD report')
    if not frame.symbol.eq(ticker).all():
        raise ValueError('Unexpected option root')
    stamps=pd.to_datetime(frame.created,utc=True)
    dates=stamps.dt.tz_convert('America/New_York').dt.tz_localize(None).dt.normalize()
    if not dates.eq(pd.Timestamp(value_date)).all():
        raise ValueError('Report timestamps do not match the requested New York date')
    if frame.duplicated(['expiration','strike','right']).any():
        raise ValueError('Duplicate dated option contracts')


def acquire(selection, output, limit_dates=None, client=None):
    """Request all expiries through 460 days, with bounded rate and resumable files."""
    dates=pd.to_datetime(pd.read_csv(selection).date).dropna().drop_duplicates().sort_values()
    if limit_dates is not None:
        dates=dates.iloc[:limit_dates]
    output.mkdir(parents=True,exist_ok=True)
    config={'ticker':'HYG','dates':dates.dt.strftime('%Y-%m-%d').tolist(),'max_dte':460,
        'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'clock':'ThetaData national EOD report; created is report time, not verified quote time',
        'method':'option_history_eod all expiries; no bid/ask-quality filtering before save'}
    path=output/'design.json'
    if path.exists() and json.loads(path.read_text())!=config:
        raise ValueError('Changed acquisition configuration; use a new directory')
    if not path.exists():
        path.write_text(json.dumps(config,indent=2)+'\n')
    if client is None:
        from thetadata import ThetaClient
        # The SDK can log session tokens at INFO; keep its logger at WARNING.
        logging.getLogger('thetadata').setLevel(logging.WARNING)
        try:
            client=ThetaClient(dataframe_type='pandas')
        except Exception as exc:
            (output/'access_error.json').write_text(json.dumps(
                {'phase':'authentication','error_type':type(exc).__name__},indent=2)+'\n')
            raise RuntimeError('ThetaData authentication failed; refresh local credentials') from None
    records=[]
    for value in dates:
        day=value.date()
        try:
            path=output/f'options_{day}.csv'
            if path.exists():
                options=pd.read_csv(path)
            else:
                options=client.option_history_eod(symbol='HYG',expiration='*',
                    start_date=day,end_date=day,max_dte=460)
                validate_report(options,day)
                options.to_csv(path,index=False)
                time.sleep(2.1)
            validate_report(options,day)
            path=output/f'spot_{day}.csv'
            if not path.exists():
                spot=client.stock_history_eod(symbol='HYG',start_date=day,end_date=day)
                if spot.empty or not {'created','close'}.issubset(spot.columns):
                    raise ValueError('Empty or incomplete spot EOD report')
                spot.to_csv(path,index=False)
                time.sleep(2.1)
            records.append({'date':str(day),'status':'acquired','option_rows':len(options),
                            'expiries':int(options.expiration.nunique())})
        except Exception as exc:
            records.append({'date':str(day),'status':'acquisition_failed',
                            'error_type':type(exc).__name__})
            pd.DataFrame(records).to_csv(output/'availability.csv',index=False)
            raise
        pd.DataFrame(records).to_csv(output/'availability.csv',index=False)
        print(str(day),'rows',len(options),flush=True)
    record={'recorded_utc':datetime.now(timezone.utc).isoformat(),'config':config,
        'hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob('*.csv')}}
    (output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')


def run_local(local=Locals.FETCH):
    """Fetch a frozen date list using the declared optional ThetaData integration."""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--limit-dates',type=int)
    args=parser.parse_args()
    if local==Locals.FETCH:
        acquire(args.selection,args.output,args.limit_dates)


if __name__=='__main__':
    run_local(local=Locals.FETCH)
