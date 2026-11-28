"""Exercise and cache regressions for the XLF distribution."""

from datetime import date
import json

import pandas as pd
import pytest

from option_chain_analytics import build_thetadata_eod_cache, load_thetadata_eod_cache


class AdjustedQuotes:
    def option_history_eod(self, **kwargs):
        return pd.DataFrame(
            [
                {'symbol': 'XLF1', 'expiration': date(2016, 10, 21), 'strike': strike, 'right': right,
                 'created': '2016-09-19T21:00:00Z', 'volume': 0, 'bid_size': 10, 'ask_size': 10,
                 'bid': mid - 0.01, 'ask': mid + 0.01}
                for strike, call, put in [(20.0, 4.0, 0.5), (22.0, 2.3, 0.8), (24.0, 0.7, 1.2)]
                for right, mid in [('CALL', call), ('PUT', put)]
            ],
        )

    def stock_history_eod(self, **kwargs):
        return pd.DataFrame(columns=['created', 'close'])


def test_adjusted_quotes_remain_loadable_without_a_basket_spot(tmp_path):
    pytest.importorskip('pyarrow')
    root = build_thetadata_eod_cache(
        'XLF1', '2016-09-19', '2016-09-19', output_dir=tmp_path, client=AdjustedQuotes(),
    )
    with pytest.raises(ValueError, match='no ThetaData EOD observations'):
        load_thetadata_eod_cache(root)

    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    manifest['spot_policy'] = 'unavailable'
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')

    adjusted = load_thetadata_eod_cache(root, start_date='2016-09-19', end_date='2016-09-19')
    assert adjusted.ticker == 'XLF1'
    assert adjusted.spot_data.empty
    assert adjusted.chain_ts['spot_price'].isna().all()
    assert adjusted.chain_ts['forward_price'].notna().all()
    assert len(adjusted.chain_ts) == 6
    assert adjusted.chain_ts['contract'].str.startswith('XLF1-').all()


def test_old_and_new_positions_follow_different_contracts():
    from option_chain_analytics.data.occ_xlf import xlf_contract_at_session

    original = 'XLF-20161021-C-22'
    adjusted = 'XLF1-20161021-C-22'
    before = date(2016, 9, 16)
    effective = date(2016, 9, 19)
    after = date(2016, 9, 20)
    assert xlf_contract_at_session(original, before, before) == original
    assert xlf_contract_at_session(original, before, effective) == adjusted
    assert xlf_contract_at_session(original, before, after) == adjusted
    assert xlf_contract_at_session(original, after, after) == original
    assert xlf_contract_at_session(adjusted, effective, after) == adjusted


def test_adjusted_exercise_uses_the_full_deliverable_and_strike_multiplier():
    from option_chain_analytics.data.occ_xlf import xlf1_intrinsic_value

    inputs = {'strike': 22.0, 'xlf_price': 19.0, 'xlre_price': 30.0}
    assert xlf1_intrinsic_value(option_type='C', cash_in_lieu=25.0, **inputs) == 115.0
    assert xlf1_intrinsic_value(option_type='P', cash_in_lieu=25.0, **inputs) == 0.0
    assert xlf1_intrinsic_value(option_type='P', cash_in_lieu=25.0, **(inputs | {'strike': 24.0})) == 85.0
    with pytest.raises(ValueError, match='verified cash in lieu'):
        xlf1_intrinsic_value(option_type='C', cash_in_lieu=float('nan'), **inputs)
