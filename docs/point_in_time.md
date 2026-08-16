# Point-in-time reconstruction

`create_chain_from_from_options_dfs` reconstructs the expiry slices available at one exact
observation timestamp. It does not choose a previous or future observation implicitly.

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

The reconstruction groups only that timestamp's rows by `mat_id`, creates one `ExpirySlice` per
maturity, and derives its forward from contemporaneous rows. Missing timestamps return `None`.

## No-look-ahead contract

- Select `value_time` from the observation index or from a point-in-time schedule known to exist.
- Do not backfill option observations from a later timestamp.
- A loader may forward-fill an independently observed spot series only when its sampling policy is
  explicit; it must not use an option observation that arrived after `value_time`.
- Use each row's contemporaneous `forward_price`, `discount`, and `ttm`; never recompute them from a
  full-sample fit inside a rolling backtest.
- Deduplicate repeated contract rows at the same timestamp according to a documented source rule.

The deterministic fixture proves the same contract's `ttm` declines across observations. For an
empirical study, add source-specific tests covering timestamps, duplicate policy, stale quotes,
timezone conversion, and the publication/arrival time of every exogenous series.
