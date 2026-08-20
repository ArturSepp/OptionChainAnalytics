# Chain and roll queries

Once reconstructed, a `SlicesChain` exposes its maturity map and each `ExpirySlice` exposes strike
and volatility queries.

```python
from option_chain_analytics import (
    NearestStrikeOnGrid,
    create_chain_at_time,
    generate_simulated_options_data,
)

options_data = generate_simulated_options_data()
value_time = options_data.get_timeindex()[0]
chain = create_chain_at_time(options_data, value_time)
front = chain.get_expiry_slice(next(iter(chain.expiry_slices)))

atm_strike = front.get_atm_option_strike(NearestStrikeOnGrid.NEAREST)
atm_vol = front.get_atm_vol(NearestStrikeOnGrid.NEAREST)
assert atm_strike == 100.0
assert atm_vol > 0.0
```

`NearestStrikeOnGrid.BELOW` means the grid strike below the target and `ABOVE` means the grid strike
above the target. Tests lock this convention because the legacy implementation once inverted it.

For calendar selection, use the roll helper:

```python
from option_chain_analytics.utils.roll_maturities import (
    RollMaturitySelection,
    get_roll_maturity_slices_at_value_time,
)

roll_ids = get_roll_maturity_slices_at_value_time(
    options_data,
    value_time,
    maturity_selection=RollMaturitySelection.WEEKLY_FRIDAY,
    is_apply_open_interest_filter=False,
    hour_offset=8,
)
assert roll_ids == ['12Jan2024']
```

The open-interest filter removes thin newly listed slices when enabled. Its threshold is a library
policy, not a universal market convention; empirical work should report whether it was applied.
