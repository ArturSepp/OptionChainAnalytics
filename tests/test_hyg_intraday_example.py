"""Synthetic point-in-time and restart tests for private quote acquisition."""
import runpy
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pandas as pd
import pytest


EXAMPLE_PATH = Path(__file__).resolve().parents[1] / 'examples' / 'fetch_hyg_intraday_quotes.py'
example = runpy.run_path(str(EXAMPLE_PATH))
acquire = example['acquire']
read_schedule = example['read_schedule']
validate_snapshot = example['validate_snapshot']


def snapshot(stamp='2023-07-31T19:54:59Z'):
    return pd.DataFrame({'symbol': ['HYG'], 'expiration': ['2024-07-19'],
                         'strike': [75.], 'right': ['CALL'], 'timestamp': [stamp],
                         'bid': [0.], 'ask': [.2], 'bid_size': [0], 'ask_size': [5],
                         'bid_condition': [50], 'ask_condition': [50]})


@pytest.mark.parametrize('stamp,match', [
    ('2023-07-31T19:55:00.001Z', 'future'),
    ('2023-07-31T15:54:59', 'timezone'),
    ('2023-07-30T19:54:59Z', 'New York quote date'),
    ('2023-07-31T23:55:00+04:00', 'future'),
])
def test_rejects_future_naive_or_wrong_day_quotes(stamp, match):
    # The +04:00 case is exactly 19:55 UTC: use an earlier NY cutoff to test conversion.
    clock = '15:54:00' if '+04:00' in stamp else '15:55:00'
    with pytest.raises(ValueError, match=match):
        validate_snapshot(snapshot(stamp), '2023-07-31', clock, 'options')


def test_half_day_and_exact_boundary_use_real_timezones():
    frame = snapshot('2024-11-29T17:55:00Z')
    frame.expiration = '2025-10-17'
    assert validate_snapshot(frame, '2024-11-29', '12:55:00', 'options').iloc[0] == 0
    frame.timestamp = '2024-11-29T18:00:00Z'
    with pytest.raises(ValueError, match='future'):
        validate_snapshot(frame, '2024-11-29', '12:55:00', 'options')


def test_mixed_fractional_second_precision_is_supported():
    frame = pd.concat([snapshot(), snapshot('2023-07-31T19:54:59.500Z')], ignore_index=True)
    frame.loc[1, 'strike'] = 76.
    assert validate_snapshot(frame, '2023-07-31', '15:55:00', 'options').tolist() == [1., .5]


def test_identity_validation_and_preservation_of_extra_maturities():
    frame = snapshot()
    frame.expiration = '2025-01-17'  # Provider returned >460 DTE; preserve raw evidence.
    assert validate_snapshot(frame, '2023-07-31', '15:55:00', 'options').iloc[0] == 1
    with pytest.raises(ValueError, match='Duplicate'):
        validate_snapshot(pd.concat([frame, frame]), '2023-07-31', '15:55:00', 'options')
    frame.symbol = 'TLT'
    with pytest.raises(ValueError, match='root'):
        validate_snapshot(frame, '2023-07-31', '15:55:00', 'options')


def test_frozen_schedule_rejects_duplicate_or_subminute_requests(tmp_path):
    path = tmp_path / 'schedule.csv'
    pd.DataFrame({'date': ['2023-07-31'] * 2, 'time_of_day': ['15:55:00'] * 2}).to_csv(path, index=False)
    with pytest.raises(ValueError, match='Duplicate'):
        read_schedule(path)
    pd.DataFrame({'date': ['2023-07-31'], 'time_of_day': ['15:55:01']}).to_csv(path, index=False)
    with pytest.raises(ValueError, match='minute boundaries'):
        read_schedule(path)


def test_zero_bid_preserved_resume_hash_checked_and_failure_not_completed(tmp_path, monkeypatch):
    def unavailable_sdk(name):
        raise PackageNotFoundError(name)

    monkeypatch.setitem(acquire.__globals__, 'version', unavailable_sdk)

    class Client:
        calls = 0

        def option_at_time_quote(self, **kwargs):
            self.calls += 1
            assert kwargs['expiration'] == '*' and kwargs['max_dte'] == 460
            return snapshot()

    path = tmp_path / 'schedule.csv'
    pd.DataFrame({'date': ['2023-07-31'], 'time_of_day': ['15:55:00']}).to_csv(path, index=False)
    client = Client()
    output = tmp_path / 'output'
    acquire(path, output, client=client, pause=0)
    acquire(path, output, client=client, pause=0)
    assert client.calls == 1
    saved = output / 'options_2023-07-31.csv'
    raw = pd.read_csv(saved)
    assert raw.bid.iloc[0] == 0
    raw.bid = .1
    raw.to_csv(saved, index=False)
    with pytest.raises(RuntimeError, match='ValueError'):
        acquire(path, output, client=client, pause=0)
    assert pd.read_csv(output / 'availability.csv').status.iloc[0] == 'failed'


def test_empty_response_cannot_be_marked_acquired(tmp_path):
    class Client:
        def option_at_time_quote(self, **kwargs):
            return snapshot().iloc[:0]

    path = tmp_path / 'schedule.csv'
    pd.DataFrame({'date': ['2023-07-31'], 'time_of_day': ['15:55:00']}).to_csv(path, index=False)
    output = tmp_path / 'output'
    with pytest.raises(RuntimeError, match='ValueError'):
        acquire(path, output, client=Client(), pause=0)
    assert not (output / 'options_2023-07-31.csv').exists()
    assert pd.read_csv(output / 'availability.csv').status.iloc[0] == 'failed'
