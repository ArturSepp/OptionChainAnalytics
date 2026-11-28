"""Exercise timestamp, snapshot and raw-separation invariants offline."""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from option_chain_analytics.data.thetadata_sync import (
    backward_stock,
    normalize,
    schedule,
    timestamps,
)

CUTOFF = pd.Timestamp('2024-11-29T17:55:00Z')


def stock(*times):
    return pd.DataFrame({'timestamp': times, 'bid': [78 + i for i in range(len(times))],
                         'ask': [78.02 + i for i in range(len(times))], 'bid_condition': 0, 'ask_condition': 0})


def options(*times):
    return pd.DataFrame({'symbol': 'HYG', 'expiration': '2025-01-17', 'strike': 78.,
                         'right': 'PUT', 'timestamp': times, 'bid': .6, 'ask': .65,
                         'bid_condition': 50, 'ask_condition': 50})


def test_calendar_close_dst_and_completion():
    events = pd.DataFrame([('2024-11-29', 'early_close', '13:00:00'), ('2024-11-28', 'full_close', None)],
                          columns=['date', 'type', 'close'])
    rows = schedule(events, date(2024, 11, 27), date(2024, 12, 2), pd.Timestamp('2024-12-02T20:59:00Z'))
    assert rows['date'].tolist() == ['2024-11-27', '2024-11-29']
    assert rows['snapshot_timestamp'].tolist() == [pd.Timestamp('2024-11-27T20:55:00Z'), CUTOFF]
    rows = schedule(events, date(2024, 3, 8), date(2024, 3, 11), pd.Timestamp('2024-03-12T00:00:00Z'))
    assert rows['snapshot_timestamp'].dt.hour.tolist() == [20, 19]


def test_naive_stamps_are_new_york_times():
    values = pd.Series(['2024-03-08 15:55:00', '2024-03-11 15:55:00', '2024-03-11T15:55:00-04:00',
                        '2024-03-10 02:30:00', '2024-11-03 01:30:00'])
    stamps = timestamps(values)
    assert stamps.iloc[0] == pd.Timestamp('2024-03-08T20:55:00Z')
    assert stamps.iloc[1] == stamps.iloc[2] == pd.Timestamp('2024-03-11T19:55:00Z')
    assert stamps.iloc[3:].isna().all()


def test_backward_reference_never_selects_next_quote_or_previous_session():
    data = stock('2024-11-27 15:55:00', '2024-11-29 12:54:58', '2024-11-29 12:55:00')
    references = timestamps(pd.Series(['2024-11-29 12:54:57', '2024-11-29 12:54:59.999',
                                       '2024-11-29 12:55:00', '2024-11-29 12:55:01']))
    actual = backward_stock(data, references, CUTOFF)
    assert actual['reference_stock_mid'].iloc[1:3].tolist() == pytest.approx([79.01, 80.01])
    assert actual['reference_stock_mid'].iloc[[0, 3]].isna().all()


def test_stock_allows_reported_subsecond_update_before_cutoff():
    snapshots = stock('2024-11-29 12:54:59.967', '2024-11-29 12:55:00.017')
    opt = options('2024-11-29 12:54:59')
    panel, audit = normalize('HYG', CUTOFF, snapshots, opt, pd.DataFrame())
    assert audit['stock_timestamp_kind'] == 'reported_event_time'
    assert audit['stock_quote_age_seconds'] == pytest.approx(.033)
    assert audit['stock_mid'] == pytest.approx(78.01)
    assert panel['eligible'].tolist() == [True]


@pytest.mark.parametrize('stamp, status', [
    ('2024-11-27 15:55:00', 'wrong_stock_session'), ('2024-11-29 12:55:01', 'future_stock'),
    ('bad timestamp', 'invalid_stock_timestamp'), (None, 'missing_stock'),
])
def test_stock_gap_has_no_provider_fallback(stamp, status):
    opt = options('2024-11-29 12:55:00')
    greek = opt.assign(underlying_price=100., underlying_timestamp='2024-11-29 12:55:00')
    panel, audit = normalize('HYG', CUTOFF, stock(stamp) if stamp else pd.DataFrame(), opt, greek)
    assert audit['quality'] == status
    assert not panel['eligible'].any() and panel['stock_mid'].isna().all()
    assert panel['provider_underlying_price'].tolist() == [100.]


def test_option_failures_are_flags_and_raw_remains_intact():
    opt = options('2024-11-27 15:55:00', '2024-11-29 12:55:01', '2024-11-29 12:49:00',
                  '2024-11-29 12:49:05', '2024-11-29 12:54:58', '2024-11-29 12:54:59')
    opt['strike'] = [77., 79., 78., 78., 80., 81.]
    opt.loc[4, 'expiration'] = '2027-01-01'
    opt.loc[5, 'bid'] = 0.
    copy = opt.copy(deep=True)
    panel, _ = normalize('HYG', CUTOFF, stock('2024-11-29 12:55:00'), opt, pd.DataFrame())
    assert panel['eligible'].tolist() == [False, False, False, False, False, True]
    assert panel.loc[0, 'flag_wrong_session'] and panel.loc[1, 'flag_future_quote']
    assert panel.loc[2:3, 'flag_duplicate_identity'].all() and panel.loc[2:3, 'option_quote_older_300s'].all()
    assert panel.loc[4, 'flag_outside_dte'] and panel.loc[5, 'option_zero_bid']
    assert panel['stock_quote_age_seconds'].isna().all()
    pd.testing.assert_frame_equal(copy, opt)


def test_provider_fields_preserved_and_temporally_matched():
    opt = options('2024-11-29 12:54:57')
    greek = options('2024-11-29 12:54:59', '2024-11-29 12:55:01')
    greek['underlying_timestamp'] = ['2024-11-29 12:54:58.800', '2024-11-29 12:55:01']
    greek['underlying_price'] = [79.02, 130.]
    greek['implied_vol'], greek['delta'], greek['vega'] = [.17, .21], [-.3, -.6], [.1, .4]
    snapshots = stock('2024-11-29 12:54:55', '2024-11-29 12:54:59', '2024-11-29 12:55:00')
    panel, _ = normalize('HYG', CUTOFF, snapshots.tail(1), opt, greek, stock_samples=snapshots)
    row = panel.iloc[0]
    assert row['provider_underlying_price'] == 79.02 and row['stock_mid'] == pytest.approx(80.01)
    assert row['provider_implied_vol'] == .17 and row['provider_delta'] == -.3 and row['provider_vega'] == .1
    assert row['provider_underlying_timestamp_raw'] == '2024-11-29 12:54:58.800'
    assert row['reference_stock_mid'] == pytest.approx(78.01)
    assert row['provider_underlying_minus_reference_mid'] == pytest.approx(1.01)
    assert np.isnan(row['stock_quote_age_seconds'])
