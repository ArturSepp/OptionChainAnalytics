import numpy as np

from option_chain_analytics import (
    NearestStrikeOnGrid,
    SliceColumn,
    create_chain_from_from_options_dfs,
    generate_simulated_options_data,
)
from option_chain_analytics.utils.roll_maturities import (
    RollMaturitySelection,
    get_roll_maturity_slices_at_value_time,
)


def test_simulated_data_is_complete_deterministic_and_point_in_time() -> None:
    first = generate_simulated_options_data()
    second = generate_simulated_options_data()

    assert first.chain_ts.equals(second.chain_ts)
    assert list(first.chain_ts.columns) == [column.value for column in SliceColumn]
    assert first.chain_ts.attrs['source'] == 'deterministic_simulation'
    assert len(first.get_timeindex()) == 2
    assert first.chain_ts.groupby(SliceColumn.EXCHANGE_TIME.value).size().eq(30).all()

    contract = first.chain_ts[SliceColumn.CONTRACT.value].iloc[0]
    history = first.get_contract_data(contract).sort_values(SliceColumn.EXCHANGE_TIME.value)
    assert len(history) == 2
    assert history[SliceColumn.TTM.value].is_monotonic_decreasing
    assert history[SliceColumn.EXPIRY.value].nunique() == 1


def test_simulated_prices_respect_spreads_and_put_call_parity() -> None:
    chain_ts = generate_simulated_options_data().chain_ts

    assert chain_ts[SliceColumn.BID_PRICE.value].le(chain_ts[SliceColumn.MARK_PRICE.value]).all()
    assert chain_ts[SliceColumn.MARK_PRICE.value].le(chain_ts[SliceColumn.ASK_PRICE.value]).all()
    assert chain_ts[SliceColumn.BID_IV.value].le(chain_ts[SliceColumn.MARK_IV.value]).all()
    assert chain_ts[SliceColumn.MARK_IV.value].le(chain_ts[SliceColumn.ASK_IV.value]).all()

    first_time = chain_ts[SliceColumn.EXCHANGE_TIME.value].min()
    first_expiry = chain_ts[SliceColumn.EXPIRY.value].min()
    frame = chain_ts.loc[
        chain_ts[SliceColumn.EXCHANGE_TIME.value].eq(first_time)
        & chain_ts[SliceColumn.EXPIRY.value].eq(first_expiry)
    ]
    calls = frame.loc[frame[SliceColumn.OPTION_TYPE.value].eq('C')].set_index(SliceColumn.STRIKE.value)
    puts = frame.loc[frame[SliceColumn.OPTION_TYPE.value].eq('P')].set_index(SliceColumn.STRIKE.value)
    parity = calls[SliceColumn.MARK_PRICE.value] - puts[SliceColumn.MARK_PRICE.value]
    expected = calls[SliceColumn.DISCOUNT.value] * (
        calls[SliceColumn.FORWARD_PRICE.value] - calls.index.to_numpy(float)
    )
    assert np.allclose(parity, expected, atol=1e-10)


def test_simulated_data_reconstructs_chain_and_roll_selection() -> None:
    options_data = generate_simulated_options_data()
    value_time = options_data.get_timeindex()[0]

    chain = create_chain_from_from_options_dfs(options_data_dfs=options_data, value_time=value_time)

    assert chain is not None
    assert list(chain.expiry_slices) == ['12Jan2024', '19Jan2024', '16Feb2024']
    first_expiry = chain.get_expiry_slice('12Jan2024')
    assert first_expiry.get_atm_option_strike(NearestStrikeOnGrid.NEAREST) == 100.0
    assert np.isfinite(first_expiry.get_atm_vol(NearestStrikeOnGrid.NEAREST))

    roll_expiries = get_roll_maturity_slices_at_value_time(
        options_data_dfs=options_data,
        value_time=value_time,
        maturity_selection=RollMaturitySelection.WEEKLY_FRIDAY,
        is_apply_open_interest_filter=False,
        hour_offset=8,
    )
    assert roll_expiries == ['12Jan2024']
