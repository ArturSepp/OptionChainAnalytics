import numpy as np
import pandas as pd

from option_chain_analytics.chain_loader_from_ts import create_chain_from_from_options_dfs
from option_chain_analytics.chain_ts import OptionsDataDFs
from option_chain_analytics.option_chain import SliceColumn
from option_chain_analytics.ts_loaders import map_vlad_options_data


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


def test_map_vlad_options_data_can_infer_bid_ask_iv() -> None:
    chain_ts = map_vlad_options_data(
        source=_source_frame(),
        ticker='SPX',
        is_compute_bid_ask_iv=True,
    )['chain_ts']

    bid_iv = chain_ts[SliceColumn.BID_IV.value]
    ask_iv = chain_ts[SliceColumn.ASK_IV.value]
    assert np.isfinite(bid_iv).all()
    assert np.isfinite(ask_iv).all()
    assert bid_iv.le(ask_iv).all()


def test_mapped_vlad_data_constructs_options_data_dfs_and_chain() -> None:
    options_data = OptionsDataDFs(**map_vlad_options_data(source=_source_frame(), ticker='SPX'))
    value_time = options_data.get_timeindex()[0]

    chain = create_chain_from_from_options_dfs(options_data_dfs=options_data, value_time=value_time)

    assert list(chain.expiry_slices) == ['19Jan2024']
    assert np.isclose(chain.get_expiry_slice('19Jan2024').get_future_price(), 5000.0)
