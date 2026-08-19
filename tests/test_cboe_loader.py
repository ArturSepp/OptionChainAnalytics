from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from option_chain_analytics.chain_loader_from_ts import create_chain_from_from_options_dfs
from option_chain_analytics.chain_ts import OptionsDataDFs
from option_chain_analytics.option_chain import SliceColumn
from option_chain_analytics.ts_loaders import (
    CBOE_CACHE_FORMAT,
    CBOE_CACHE_SCHEMA_VERSION,
    TARDIS_EOD_CACHE_FORMAT,
    TARDIS_EOD_CACHE_SCHEMA_VERSION,
    build_local_cboe_options_cache,
    build_local_tardis_eod_options_cache,
    load_local_cboe_options_data,
    load_local_tardis_eod_options_data,
    map_cboe_options_data,
    reconstruct_cboe_source_analytics,
)


def _source_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            'exdate': pd.to_datetime(['2024-01-19'] * 4),
            'strike_price': [4900, 4900, 5000, 5000],
            'cp_flag': ['c', 'p', 'c', 'p'],
            'mid_price': [130.0, 30.0, 65.0, 65.0],
            'bid_size': [10, 10, 10, 10],
            'best_bid': [129.0, 29.0, 64.0, 64.0],
            'offer_size': [12, 12, 12, 12],
            'best_offer': [131.0, 31.0, 66.0, 66.0],
            'open_interest': [100, 100, 200, 200],
            'date': pd.to_datetime(['2024-01-02 16:00:00'] * 4),
            'impl_df': [1.0] * 4,
            'impl_fw': [5000.0] * 4,
            'mid_vols': [0.20, 0.20, 0.18, 0.18],
            'dte': [17.0 / 365.0] * 4,
            'vega': [4.0, 4.0, 5.0, 5.0],
            'delta': [0.70, -0.30, 0.50, -0.50],
        }
    )


def test_map_cboe_options_data_builds_complete_chain_schema() -> None:
    mapped = map_cboe_options_data(source=_source_frame(), ticker='SPX')
    chain_ts = mapped['chain_ts']

    assert list(chain_ts.columns) == [column.value for column in SliceColumn]
    assert chain_ts[SliceColumn.CONTRACT.value].nunique() == 4
    assert str(chain_ts[SliceColumn.EXCHANGE_TIME.value].dt.tz) == 'UTC'
    assert chain_ts[SliceColumn.EXCHANGE_TIME.value].iloc[0] == pd.Timestamp('2024-01-02 21:00:00+00:00')
    assert chain_ts[SliceColumn.EXPIRY.value].iloc[0] == pd.Timestamp('2024-01-19 21:00:00+00:00')
    expected_ttm = (pd.Timestamp('2024-01-19 21:00:00+00:00') - pd.Timestamp('2024-01-02 21:00:00+00:00'))
    assert np.isclose(
        chain_ts[SliceColumn.TTM.value].iloc[0],
        expected_ttm.total_seconds() / (365.0 * 24.0 * 60.0 * 60.0),
    )
    assert chain_ts[SliceColumn.DISCOUNT.value].eq(1.0).all()
    assert chain_ts[SliceColumn.CONTRACT_SIZE.value].eq(100.0).all()
    assert np.isfinite(chain_ts[SliceColumn.BID_IV.value]).all()
    assert np.isfinite(chain_ts[SliceColumn.ASK_IV.value]).all()
    assert chain_ts[SliceColumn.BID_IV.value].le(chain_ts[SliceColumn.ASK_IV.value]).all()
    assert mapped['spot_data']['close'].isna().all()


def test_map_cboe_options_data_can_use_explicit_front_forward_proxy() -> None:
    mapped = map_cboe_options_data(
        source=_source_frame(),
        ticker='SPX',
        is_use_front_forward_as_spot=True,
    )

    assert mapped['spot_data']['close'].iloc[0] == 5000.0
    assert mapped['spot_data'].attrs['spot_source'] == 'front_forward_proxy'
    assert mapped['chain_ts'][SliceColumn.SPOT_PRICE.value].eq(5000.0).all()


def test_map_cboe_options_data_always_infers_bid_ask_iv() -> None:
    chain_ts = map_cboe_options_data(source=_source_frame(), ticker='SPX')['chain_ts']

    bid_iv = chain_ts[SliceColumn.BID_IV.value]
    ask_iv = chain_ts[SliceColumn.ASK_IV.value]
    assert np.isfinite(bid_iv).all()
    assert np.isfinite(ask_iv).all()
    assert bid_iv.le(ask_iv).all()


def test_map_cboe_options_data_marks_non_invertible_quotes_as_nan() -> None:
    source = _source_frame()
    source.loc[0, 'strike_price'] = 0.0

    chain_ts = map_cboe_options_data(source=source, ticker='SPX')['chain_ts']
    invalid_contract = chain_ts[SliceColumn.STRIKE.value].eq(0.0)

    assert chain_ts.loc[invalid_contract, SliceColumn.BID_IV.value].isna().all()
    assert chain_ts.loc[invalid_contract, SliceColumn.ASK_IV.value].isna().all()


def test_map_cboe_vix_data_uses_morning_soq_expiry() -> None:
    source = _source_frame().assign(
        date=pd.Timestamp('2024-01-18 16:00:00'),
        exdate=pd.Timestamp('2024-01-19'),
    )

    chain_ts = map_cboe_options_data(source=source, ticker='VIX')['chain_ts']

    assert chain_ts[SliceColumn.EXPIRY.value].iloc[0] == pd.Timestamp('2024-01-19 14:30:00+00:00')
    expected_ttm = 17.5 / (365.0 * 24.0)
    assert np.isclose(chain_ts[SliceColumn.TTM.value].iloc[0], expected_ttm)


def test_reconstruct_cboe_analytics_replaces_stale_fitted_terms() -> None:
    source = _source_frame().assign(impl_df=1.38, impl_fw=4900.0, mid_vols=np.nan)

    reconstructed = reconstruct_cboe_source_analytics(source=source, ticker='SPX')

    assert np.allclose(reconstructed['impl_df'], 1.0)
    assert np.allclose(reconstructed['impl_fw'], 5000.0)
    assert np.isfinite(reconstructed['mid_vols']).all()
    assert np.isfinite(reconstructed['delta']).all()
    assert np.isfinite(reconstructed['vega']).all()


def test_mapped_cboe_data_constructs_options_data_dfs_and_chain() -> None:
    options_data = OptionsDataDFs(**map_cboe_options_data(source=_source_frame(), ticker='SPX'))
    value_time = options_data.get_timeindex()[0]

    chain = create_chain_from_from_options_dfs(options_data_dfs=options_data, value_time=value_time)

    assert list(chain.expiry_slices) == ['19Jan2024']
    assert np.isclose(chain.get_expiry_slice('19Jan2024').get_future_price(), 5000.0)


def _write_cboe_source(directory: Path, ticker: str, source: pd.DataFrame) -> Path:
    pytest.importorskip('pyarrow')
    source_path = directory.joinpath(f"{ticker.lower()}_options.feather")
    source.reset_index(drop=True).to_feather(source_path)
    return source_path


def test_cboe_normalized_parquet_cache_round_trip_and_date_filter(tmp_path: Path) -> None:
    pq = pytest.importorskip('pyarrow.parquet')
    source = pd.concat(
        [
            _source_frame(),
            _source_frame().assign(
                date=pd.Timestamp('2024-01-03 16:00:00'),
                exdate=pd.Timestamp('2024-01-26'),
            ),
        ],
        ignore_index=True,
    )
    _write_cboe_source(directory=tmp_path, ticker='SPX', source=source)

    cache_path = build_local_cboe_options_cache(ticker='SPX', local_path=str(tmp_path))
    loaded = load_local_cboe_options_data(
        ticker='SPX',
        local_path=str(tmp_path),
        start=pd.Timestamp('2024-01-03'),
        end=pd.Timestamp('2024-01-03'),
    )

    assert cache_path.name == 'spx_options_oca.parquet'
    metadata = pq.ParquetFile(cache_path).metadata.metadata
    assert metadata[b'oca_cache_format'].decode() == CBOE_CACHE_FORMAT
    assert metadata[b'oca_cache_schema_version'].decode() == CBOE_CACHE_SCHEMA_VERSION
    assert metadata[b'oca_settlement_policy'].decode() == 'spxw_pm_1600_new_york'
    assert metadata[b'oca_analytics'].decode() == 'parity_huber_vip_bsm'
    assert loaded['chain_ts'][SliceColumn.EXCHANGE_TIME.value].nunique() == 1
    assert loaded['chain_ts'][SliceColumn.EXCHANGE_TIME.value].iloc[0] == pd.Timestamp(
        '2024-01-03 21:00:00+00:00'
    )
    assert np.isfinite(loaded['chain_ts'][SliceColumn.BID_IV.value]).all()
    assert np.isfinite(loaded['chain_ts'][SliceColumn.ASK_IV.value]).all()


def test_cboe_loader_rejects_cache_when_source_changes(tmp_path: Path) -> None:
    source_path = _write_cboe_source(directory=tmp_path, ticker='VIX', source=_source_frame())
    build_local_cboe_options_cache(ticker='VIX', local_path=str(tmp_path))
    changed_source = pd.concat([_source_frame(), _source_frame()], ignore_index=True)
    changed_source.to_feather(source_path)

    with pytest.raises(ValueError, match='incompatible or stale CBOE cache'):
        load_local_cboe_options_data(ticker='VIX', local_path=str(tmp_path))


def _write_tardis_sources(directory: Path, ticker: str = 'BTC') -> tuple[Path, Path]:
    pytest.importorskip('pyarrow')
    exchange_times = pd.to_datetime(
        [
            '2024-01-02 07:00:00+00:00',
            '2024-01-02 07:00:00+00:00',
            '2024-01-02 08:00:00+00:00',
            '2024-01-02 08:00:00+00:00',
            '2024-01-03 08:00:00+00:00',
            '2024-01-03 08:00:00+00:00',
        ]
    )
    expiry = pd.Timestamp('2024-01-26 08:00:00+00:00')
    option_types = ['C', 'P'] * 3
    strikes = [50_000.0, 50_000.0, 51_000.0, 51_000.0, 52_000.0, 52_000.0]
    source = pd.DataFrame(
        {
            'contract': [f'{ticker}-26JAN24-{strike:.0f}-{option_type}' for strike, option_type in zip(strikes, option_types)],
            'exchange_time': exchange_times,
            'underlying_index': [f'{ticker}-26JAN24'] * 6,
            'underlying_price': [50_100.0, 50_100.0, 51_100.0, 51_100.0, 52_100.0, 52_100.0],
            'usd_multiplier': [50_100.0, 50_100.0, 51_100.0, 51_100.0, 52_100.0, 52_100.0],
            'mark_price': [0.05, 0.04, 0.06, 0.05, 0.07, 0.06],
            'bid_price': [0.049, 0.039, 0.059, 0.049, 0.069, 0.059],
            'ask_price': [0.051, 0.041, 0.061, 0.051, 0.071, 0.061],
            'bid_size': [2.0] * 6,
            'ask_size': [3.0] * 6,
            'mark_iv': [0.60] * 6,
            'bid_iv': [0.59] * 6,
            'ask_iv': [0.61] * 6,
            'delta': [0.50, -0.50] * 3,
            'vega': [10.0] * 6,
            'theta': [-2.0] * 6,
            'gamma': [0.001] * 6,
            'open_interest': [100.0] * 6,
            'volume': [5.0] * 6,
            'mat_id': ['26Jan2024'] * 6,
            'strike': strikes,
            'optiontype': option_types,
            'expiry': [expiry] * 6,
            'ttm': [24.0 / 365.0] * 6,
            'contract_size': [0.1] * 6,
            'interest_rate': [0.0] * 6,
        }
    )
    spot = pd.DataFrame(
        {
            'timestamp': pd.to_datetime(
                [
                    '2024-01-02 07:00:00+00:00',
                    '2024-01-02 08:00:00+00:00',
                    '2024-01-03 08:00:00+00:00',
                ]
            ),
            'index_price': [50_000.0, 51_000.0, 52_000.0],
        }
    )
    source_path = directory.joinpath(f'{ticker}_freq_H.feather')
    spot_path = directory.joinpath(f'{ticker}_perp_freq_H.feather')
    source.to_feather(source_path)
    spot.to_feather(spot_path)
    return source_path, spot_path


def test_tardis_eod_cache_uses_exact_utc_cut_and_canonical_schema(tmp_path: Path) -> None:
    pa = pytest.importorskip('pyarrow')
    pq = pytest.importorskip('pyarrow.parquet')
    _write_tardis_sources(directory=tmp_path)
    _write_cboe_source(directory=tmp_path, ticker='SPX', source=_source_frame())

    crypto_cache = build_local_tardis_eod_options_cache(ticker='BTC', local_path=str(tmp_path))
    cboe_cache = build_local_cboe_options_cache(ticker='SPX', local_path=str(tmp_path))
    loaded = load_local_tardis_eod_options_data(
        ticker='BTC',
        local_path=str(tmp_path),
        start=pd.Timestamp('2024-01-03'),
        end=pd.Timestamp('2024-01-03'),
    )

    crypto_schema = pq.read_schema(crypto_cache).remove_metadata()
    cboe_schema = pq.read_schema(cboe_cache).remove_metadata()
    assert crypto_schema.equals(cboe_schema)
    assert all(
        field.type == pa.float64()
        for field in crypto_schema
        if field.name not in {'contract', 'underlying_index', 'mat_id', 'optiontype', 'exchange_time', 'expiry'}
    )
    assert loaded['chain_ts'][SliceColumn.EXCHANGE_TIME.value].unique().tolist() == [
        pd.Timestamp('2024-01-03 08:00:00+00:00')
    ]
    assert loaded['spot_data']['close'].iloc[0] == 52_000.0
    assert list(loaded['chain_ts'].columns) == [column.value for column in SliceColumn]
    metadata = pq.ParquetFile(crypto_cache).metadata.metadata
    assert metadata[b'oca_cache_format'].decode() == TARDIS_EOD_CACHE_FORMAT
    assert metadata[b'oca_cache_schema_version'].decode() == TARDIS_EOD_CACHE_SCHEMA_VERSION
    assert metadata[b'oca_observation_policy'].decode() == 'exact_0800_utc'


def test_tardis_eod_cache_uses_exact_option_index_when_perpetual_spot_is_missing(tmp_path: Path) -> None:
    source_path, spot_path = _write_tardis_sources(directory=tmp_path)
    source = pd.read_feather(source_path)
    is_fallback_time = source['exchange_time'].eq(pd.Timestamp('2024-01-03 08:00:00+00:00'))
    source.loc[is_fallback_time, 'underlying_index'] = 'index_price'
    source.loc[is_fallback_time, 'underlying_price'] = 51_975.0
    source.to_feather(source_path)
    spot = pd.read_feather(spot_path)
    spot = spot.loc[spot['timestamp'].ne(pd.Timestamp('2024-01-03 08:00:00+00:00'))]
    spot.to_feather(spot_path)

    build_local_tardis_eod_options_cache(ticker='BTC', local_path=str(tmp_path))
    loaded = load_local_tardis_eod_options_data(
        ticker='BTC',
        local_path=str(tmp_path),
        start=pd.Timestamp('2024-01-03'),
        end=pd.Timestamp('2024-01-03'),
    )

    assert loaded['spot_data']['close'].iloc[0] == 51_975.0


def test_tardis_eod_loader_rejects_cache_when_source_changes(tmp_path: Path) -> None:
    source_path, _ = _write_tardis_sources(directory=tmp_path)
    build_local_tardis_eod_options_cache(ticker='BTC', local_path=str(tmp_path))
    source = pd.read_feather(source_path)
    pd.concat([source, source.iloc[[0]]], ignore_index=True).to_feather(source_path)

    with pytest.raises(ValueError, match='incompatible or stale Tardis EOD cache'):
        load_local_tardis_eod_options_data(ticker='BTC', local_path=str(tmp_path))
