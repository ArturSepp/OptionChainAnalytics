# Point-in-time reconstruction

`create_chain_from_from_options_dfs` reconstructs the expiry slices available at one observation
timestamp. Exact selection remains the default. Scheduled studies may explicitly request the
latest observation at or before the schedule time with `time_selection="previous"`.

```python
from option_chain_analytics import (
    create_chain_from_from_options_dfs,
    generate_simulated_options_data,
)

options_data = generate_simulated_options_data()
value_time = options_data.get_timeindex()[0]
chain = create_chain_from_from_options_dfs(options_data, value_time)
assert chain is not None
assert chain.value_time == value_time
```

```python
import pandas as pd

scheduled_time = value_time + pd.Timedelta(hours=2)
chain = create_chain_from_from_options_dfs(
    options_data,
    scheduled_time,
    time_selection="previous",
)
assert chain.value_time == value_time
```

The reconstruction groups only the selected timestamp's rows by `mat_id`, creates one
`ExpirySlice` per maturity, and derives its forward from contemporaneous rows. Missing exact
timestamps return `None`; a `previous` request before the first observation also returns `None`.
`create_chain_timeseries` uses `previous` by default because its input is a sampling schedule;
pass `time_selection="exact"` when exact feed-time matching is required.

## No-look-ahead contract

- Select `value_time` from the observation index, or use the explicit `previous` policy for a
  point-in-time schedule that does not necessarily coincide with the feed timestamp.
- Do not backfill option observations from a later timestamp.
- A loader may forward-fill an independently observed spot series only when its sampling policy is
  explicit; it must not use an option observation that arrived after `value_time`.
- Use each row's contemporaneous `forward_price`, `discount`, and `ttm`; never recompute them from a
  full-sample fit inside a rolling backtest.
- Deduplicate repeated contract rows at the same timestamp according to a documented source rule.

The deterministic fixture proves the same contract's `ttm` declines across observations. For an
empirical study, add source-specific tests covering timestamps, duplicate policy, stale quotes,
timezone conversion, and the publication/arrival time of every exogenous series.
