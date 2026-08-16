"""Offline first success: construct and query a deterministic option panel."""

from option_chain_analytics import (
    NearestStrikeOnGrid,
    create_chain_from_from_options_dfs,
    generate_simulated_options_data,
)
from option_chain_analytics.utils.roll_maturities import (
    RollMaturitySelection,
    get_roll_maturity_slices_at_value_time,
)


def main() -> None:
    options_data = generate_simulated_options_data()
    value_time = options_data.get_timeindex()[0]
    chain = create_chain_from_from_options_dfs(options_data_dfs=options_data, value_time=value_time)
    if chain is None:
        raise RuntimeError('the deterministic panel did not produce a chain')

    first_expiry_id = next(iter(chain.expiry_slices))
    first_expiry = chain.get_expiry_slice(first_expiry_id)
    roll_expiries = get_roll_maturity_slices_at_value_time(
        options_data_dfs=options_data,
        value_time=value_time,
        maturity_selection=RollMaturitySelection.WEEKLY_FRIDAY,
        is_apply_open_interest_filter=False,
        hour_offset=8,
    )

    print(f'ticker={options_data.ticker}')
    print(f'observation_times={len(options_data.get_timeindex())}')
    print(f'contracts_at_first_time={len(chain.options_df)}')
    print(f'expiries={list(chain.expiry_slices)}')
    print(
        'first_expiry_atm='
        f'{first_expiry.get_atm_option_strike(NearestStrikeOnGrid.NEAREST):.2f}, '
        f'vol={first_expiry.get_atm_vol(NearestStrikeOnGrid.NEAREST):.4f}'
    )
    print(f'weekly_roll_expiries={roll_expiries}')


if __name__ == '__main__':
    main()
