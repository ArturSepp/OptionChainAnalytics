"""Offline provider-boundary tests for the dated HYG acquisition example."""
import runpy
from pathlib import Path

import pandas as pd
import pytest

EXAMPLE_PATH = Path(__file__).resolve().parents[1] / 'examples' / 'fetch_hyg_quote_audit.py'
example = runpy.run_path(str(EXAMPLE_PATH))
acquire = example['acquire']
validate_report = example['validate_report']


def report():
    return pd.DataFrame({'symbol':['HYG'],'expiration':['2024-07-19'],
        'strike':[75.],'right':['CALL'],'created':['2023-07-31T21:15:00Z'],
        'bid':[.01],'ask':[.1],'bid_size':[1],'ask_size':[1]})


def test_report_date_root_and_duplicates_are_validated():
    frame = report()
    validate_report(frame, '2023-07-31')
    with pytest.raises(ValueError,match='New York date'):
        validate_report(frame,'2023-08-01')
    with pytest.raises(ValueError,match='Duplicate'):
        validate_report(pd.concat([frame,frame]),'2023-07-31')
    frame['symbol']='TLT'
    with pytest.raises(ValueError,match='root'):
        validate_report(frame,'2023-07-31')


def test_wide_raw_quotes_survive_acquisition_and_completed_files_resume(tmp_path,monkeypatch):
    monkeypatch.setattr(example['time'], 'sleep', lambda _: None)
    class Client:
        calls=0
        def option_history_eod(self,**kwargs):
            self.calls+=1
            assert kwargs['expiration']=='*' and kwargs['max_dte']==460
            return report()
        def stock_history_eod(self,**kwargs):
            return pd.DataFrame({'created':['2023-07-31T21:10:00Z'],'close':[75.]})
    selection=tmp_path/'dates.csv'
    pd.DataFrame({'date':['2023-07-31']}).to_csv(selection,index=False)
    client=Client()
    acquire(selection,tmp_path/'output',client=client)
    acquire(selection,tmp_path/'output',client=client)
    assert client.calls==1
    raw=pd.read_csv(tmp_path/'output/options_2023-07-31.csv')
    assert raw.bid.iloc[0]==.01 and raw.ask.iloc[0]==.1


def test_provider_failure_is_not_saved_as_empty_quote_data(tmp_path):
    class Client:
        def option_history_eod(self,**kwargs):
            raise RuntimeError('provider unavailable')
    selection=tmp_path/'dates.csv'
    pd.DataFrame({'date':['2023-07-31']}).to_csv(selection,index=False)
    with pytest.raises(RuntimeError,match='provider unavailable'):
        acquire(selection,tmp_path/'output',client=Client())
    assert not (tmp_path/'output/options_2023-07-31.csv').exists()
    state=pd.read_csv(tmp_path/'output/availability.csv')
    assert state.status.iloc[0]=='acquisition_failed'
