from __future__ import annotations

import json
import runpy
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import vanilla_option_pricers as bsm

from option_chain_analytics import (
    SliceColumn,
    build_thetadata_eod_cache,
    load_thetadata_eod_cache,
)
from option_chain_analytics.data.cache import _get_oca_options_arrow_schema

pq = pytest.importorskip('pyarrow.parquet')
EXAMPLE_PATH = Path(__file__).resolve().parents[1].joinpath(
    'examples', 'build_thetadata_eod_cache.py'
)
create_thetadata_options_data = runpy.run_path(str(EXAMPLE_PATH))[
    'create_thetadata_options_data'
]

REPORT_DATES = (date(2026, 8, 17), date(2026, 8, 18))
EXPIRATION = date(2026, 9, 18)


def _option_rows() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    expiry_time = pd.Timestamp('2026-09-18 16:00:00', tz='America/New_York')
    for report_date in REPORT_DATES:
        report_time = pd.Timestamp(report_date).tz_localize('America/New_York') + pd.Timedelta(
            hours=17, minutes=15
        )
        ttm = (expiry_time - report_time).total_seconds() / (365.0 * 24.0 * 60.0 * 60.0)
        for strike in (95.0, 100.0, 105.0):
            for right, option_type in (('CALL', 'C'), ('PUT', 'P')):
                mark = bsm.compute_bsm_vanilla_price(
                    ttm=ttm,
                    forward=102.0,
                    strike=strike,
                    optiontype=option_type,
                    vol=0.25,
                    discfactor=0.995,
                )
                rows.append(
                    {
                        'symbol': 'SPY',
                        'expiration': EXPIRATION,
                        'strike': strike,
                        'right': right,
                        'created': report_time,
                        'volume': 10,
                        'bid_size': 5,
                        'bid': mark - 0.01,
                        'ask_size': 6,
                        'ask': mark + 0.01,
                    }
                )
    return pd.DataFrame(rows)


def _spot_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            'created': [
                pd.Timestamp(report_date).tz_localize('America/New_York')
                + pd.Timedelta(hours=17, minutes=10)
                for report_date in REPORT_DATES
            ],
            'close': [100.0, 101.0],
        }
    )


@dataclass
class FakeBulkThetaDataClient:
    option_calls: list[dict[str, Any]] = field(default_factory=list)
    stock_calls: list[dict[str, Any]] = field(default_factory=list)

    def option_history_eod(self, **kwargs: Any) -> pd.DataFrame:
        self.option_calls.append(kwargs)
        assert kwargs == {
            'start_date': REPORT_DATES[0],
            'end_date': REPORT_DATES[1],
            'symbol': 'SPY',
            'expiration': '*',
            'max_dte': 60,
            'strike_range': 20,
        }
        return _option_rows()

    def stock_history_eod(self, **kwargs: Any) -> pd.DataFrame:
        self.stock_calls.append(kwargs)
        assert kwargs == {
            'symbol': 'SPY',
            'start_date': REPORT_DATES[0],
            'end_date': REPORT_DATES[1],
        }
        return _spot_rows()


def test_thetadata_cache_bulk_round_trip_and_resume(tmp_path: Path) -> None:
    client = FakeBulkThetaDataClient()

    cache_root = build_thetadata_eod_cache(
        ticker='SPY',
        start_date=REPORT_DATES[0],
        end_date=REPORT_DATES[1],
        output_dir=tmp_path.joinpath('spy'),
        client=client,
    )

    options_path = cache_root.joinpath('options', '2026-08.parquet')
    spot_path = cache_root.joinpath('spot', '2026-08.parquet')
    assert options_path.is_file()
    assert spot_path.is_file()
    assert pq.read_schema(options_path).remove_metadata().equals(_get_oca_options_arrow_schema())
    metadata = pq.read_schema(options_path).metadata or {}
    assert metadata[b'provider'].decode() == 'thetadata_option_eod'
    assert metadata[b'rate_policy'].decode() == 'parity_only'

    options_data = load_thetadata_eod_cache(cache_root)
    assert options_data.ticker == 'SPY'
    assert len(options_data.chain_ts) == 12
    assert len(options_data.get_timeindex()) == 2
    assert len(options_data.spot_data) == 2
    assert str(options_data.chain_ts[SliceColumn.EXCHANGE_TIME.value].dt.tz) == 'UTC'
    assert str(options_data.chain_ts[SliceColumn.EXPIRY.value].dt.tz) == 'UTC'

    manifest = json.loads(cache_root.joinpath('manifest.json').read_text(encoding='utf-8'))
    assert manifest['configuration']['min_dte'] == 0
    assert manifest['configuration']['max_dte'] == 60
    assert manifest['configuration']['strike_range'] == 20
    filtered = load_thetadata_eod_cache(
        cache_root,
        start_date=REPORT_DATES[1],
        end_date=REPORT_DATES[1],
    )
    assert len(filtered.chain_ts) == 6
    assert len(filtered.get_timeindex()) == 1
    assert len(filtered.spot_data) == 1

    build_thetadata_eod_cache(
        ticker='SPY',
        start_date=REPORT_DATES[0],
        end_date=REPORT_DATES[1],
        output_dir=cache_root,
        client=client,
    )
    assert len(client.option_calls) == 1
    assert len(client.stock_calls) == 1


def test_thetadata_cache_default_uses_oca_cache_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An omitted output directory writes beneath the normalized-cache root."""
    cache_base = tmp_path.joinpath('normalized-caches')
    monkeypatch.setenv('OCA_CACHE_PATH', str(cache_base))

    cache_root = build_thetadata_eod_cache(
        ticker='SPY',
        start_date=REPORT_DATES[0],
        end_date=REPORT_DATES[1],
        client=FakeBulkThetaDataClient(),
    )

    assert cache_root == cache_base.joinpath('thetadata_options', 'spy').resolve()
    assert cache_root.joinpath('manifest.json').is_file()


def test_callable_example_returns_one_complete_options_data_container(tmp_path: Path) -> None:
    cache_root = tmp_path.joinpath('spy')

    options_data = create_thetadata_options_data(
        ticker='SPY',
        start_date=REPORT_DATES[0],
        end_date=REPORT_DATES[1],
        output_dir=cache_root,
        client=FakeBulkThetaDataClient(),
    )

    assert options_data.ticker == 'SPY'
    assert len(options_data.chain_ts) == 12
    assert len(options_data.get_timeindex()) == 2
    assert len(options_data.spot_data) == 2
    assert [path.name for path in cache_root.joinpath('options').glob('*.parquet')] == [
        '2026-08.parquet'
    ]
