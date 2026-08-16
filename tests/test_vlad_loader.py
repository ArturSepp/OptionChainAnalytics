from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from option_chain_analytics.chain_loader_from_ts import create_chain_from_from_options_dfs
from option_chain_analytics.chain_ts import OptionsDataDFs
from option_chain_analytics.option_chain import SliceColumn
from option_chain_analytics.ts_loaders import (
    VLAD_CACHE_FORMAT,
    VLAD_CACHE_SCHEMA_VERSION,
    build_local_cboe_options_cache,
    load_local_vlad_options_data,
    map_vlad_options_data,
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


def test_map_vlad_options_data_builds_complete_chain_schema() -> None:
    mapped = map_vlad_options_data(source=_source_frame(), ticker='SPX')
    chain_ts = mapped['chain_ts']

    assert list(chain_ts.columns) == [column.value for column in SliceColumn]
    assert chain_ts[SliceColumn.CONTRACT.value].nunique() == 4
    assert str(chain_ts[SliceColumn.EXCHANGE_TIME.value].dt.tz) == 'UTC'
    assert chain_ts[SliceColumn.EXCHANGE_TIME.value].iloc[0] == pd.Timestamp('2024-01-02 21:00:00+00:00')
    assert chain_ts[SliceColumn.EXPIRY.value].iloc[0] == pd.Timestamp('2024-01-19 21:15:00+00:00')
    assert chain_ts[SliceColumn.DISCOUNT.value].eq(1.0).all()
    assert chain_ts[SliceColumn.CONTRACT_SIZE.value].eq(100.0).all()
    assert np.isfinite(chain_ts[SliceColumn.BID_IV.value]).all()
    assert np.isfinite(chain_ts[SliceColumn.ASK_IV.value]).all()
    assert chain_ts[SliceColumn.BID_IV.value].le(chain_ts[SliceColumn.ASK_IV.value]).all()
    assert mapped['spot_data']['close'].isna().all()


def test_map_vlad_options_data_can_use_explicit_front_forward_proxy() -> None:
    mapped = map_vlad_options_data(
        source=_source_frame(),
        ticker='SPX',
        is_use_front_forward_as_spot=True,
    )

    assert mapped['spot_data']['close'].iloc[0] == 5000.0
    assert mapped['spot_data'].attrs['spot_source'] == 'front_forward_proxy'
    assert mapped['chain_ts'][SliceColumn.SPOT_PRICE.value].eq(5000.0).all()


def test_map_vlad_options_data_always_infers_bid_ask_iv() -> None:
    chain_ts = map_vlad_options_data(source=_source_frame(), ticker='SPX')['chain_ts']

    bid_iv = chain_ts[SliceColumn.BID_IV.value]
    ask_iv = chain_ts[SliceColumn.ASK_IV.value]
    assert np.isfinite(bid_iv).all()
    assert np.isfinite(ask_iv).all()
    assert bid_iv.le(ask_iv).all()


def test_map_vlad_options_data_marks_non_invertible_quotes_as_nan() -> None:
    source = _source_frame()
    source.loc[0, 'strike_price'] = 0.0

    chain_ts = map_vlad_options_data(source=source, ticker='SPX')['chain_ts']
    invalid_contract = chain_ts[SliceColumn.STRIKE.value].eq(0.0)

    assert chain_ts.loc[invalid_contract, SliceColumn.BID_IV.value].isna().all()
    assert chain_ts.loc[invalid_contract, SliceColumn.ASK_IV.value].isna().all()


def test_mapped_vlad_data_constructs_options_data_dfs_and_chain() -> None:
    options_data = OptionsDataDFs(**map_vlad_options_data(source=_source_frame(), ticker='SPX'))
    value_time = options_data.get_timeindex()[0]

    chain = create_chain_from_from_options_dfs(options_data_dfs=options_data, value_time=value_time)

    assert list(chain.expiry_slices) == ['19Jan2024']
    assert np.isclose(chain.get_expiry_slice('19Jan2024').get_future_price(), 5000.0)


def _write_vlad_source(directory: Path, ticker: str, source: pd.DataFrame) -> Path:
    pytest.importorskip('pyarrow')
    source_path = directory.joinpath(f"{ticker.lower()}_options.feather")
    source.reset_index(drop=True).to_feather(source_path)
    return source_path


def test_vlad_normalized_parquet_cache_round_trip_and_date_filter(tmp_path: Path) -> None:
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
    _write_vlad_source(directory=tmp_path, ticker='SPX', source=source)

    cache_path = build_local_cboe_options_cache(ticker='SPX', local_path=str(tmp_path))
    loaded = load_local_vlad_options_data(
        ticker='SPX',
        local_path=str(tmp_path),
        start=pd.Timestamp('2024-01-03'),
        end=pd.Timestamp('2024-01-03'),
    )

    assert cache_path.name == 'spx_options_oca.parquet'
    metadata = pq.ParquetFile(cache_path).metadata.metadata
    assert metadata[b'oca_cache_format'].decode() == VLAD_CACHE_FORMAT
    assert metadata[b'oca_cache_schema_version'].decode() == VLAD_CACHE_SCHEMA_VERSION
    assert loaded['chain_ts'][SliceColumn.EXCHANGE_TIME.value].nunique() == 1
    assert loaded['chain_ts'][SliceColumn.EXCHANGE_TIME.value].iloc[0] == pd.Timestamp(
        '2024-01-03 21:00:00+00:00'
    )
    assert np.isfinite(loaded['chain_ts'][SliceColumn.BID_IV.value]).all()
    assert np.isfinite(loaded['chain_ts'][SliceColumn.ASK_IV.value]).all()


def test_vlad_loader_rejects_cache_when_source_changes(tmp_path: Path) -> None:
    source_path = _write_vlad_source(directory=tmp_path, ticker='VIX', source=_source_frame())
    build_local_cboe_options_cache(ticker='VIX', local_path=str(tmp_path))
    changed_source = pd.concat([_source_frame(), _source_frame()], ignore_index=True)
    changed_source.to_feather(source_path)

    with pytest.raises(ValueError, match='incompatible or stale Vlad cache'):
        load_local_vlad_options_data(ticker='VIX', local_path=str(tmp_path))
