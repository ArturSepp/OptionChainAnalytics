# `OptionsDataDFs` schema

`OptionsDataDFs(chain_ts, spot_data, ticker)` holds a long option-observation panel and an aligned
underlying frame. `chain_ts` contains one row per contract and observation time. `spot_data` uses a
timezone-aware `DatetimeIndex` and must contain `close`; crypto workflows may add `mark_price` and
`funding_rate`.

## Option columns

The native `SliceColumn` fields are:

| Column | Meaning and expected representation |
|---|---|
| `contract` | Stable string identifier for the option contract. |
| `exchange_time` | Timezone-aware source observation time; UTC is preferred. |
| `underlying_index` | String identifier for the underlying or reference index. |
| `forward_price` | Forward level for this expiry, in the source quote currency. |
| `spot_price` | Contemporaneous spot level when supplied; missing is preferable to a disguised forward proxy. |
| `usd_multiplier` | Multiplier converting a quoted option price to USD value; `1.0` for USD-quoted linear options. |
| `mark_price` | Mark/mid option price in the source quote convention. |
| `bid_price`, `ask_price` | Best bid and ask in the same units as `mark_price`; may be missing. |
| `bid_size`, `ask_size` | Source quote sizes; adapter documentation must state whether these are contracts or units. |
| `mark_iv`, `bid_iv`, `ask_iv` | Annualised implied volatility as a decimal (`0.20` = 20%); missing when inversion is unavailable. |
| `delta` | Option delta. Sign follows option type; adapter documentation must state spot/forward convention. |
| `vega` | Vega in the source/pricer scale; the adapter must state whether it is per unit or percentage-point volatility. |
| `theta` | Theta in the source/pricer scale; the adapter must state its time unit. |
| `gamma` | Gamma in the source/pricer scale. |
| `open_interest` | Number of open contracts; may be missing. |
| `volume` | Source-period traded contract count; the source period must be documented. |
| `mat_id` | Stable maturity/slice label, conventionally `DDMonYYYY`. |
| `strike` | Positive strike in the same underlying-price units as `forward_price`. |
| `optiontype` | `C` for a call or `P` for a put. |
| `expiry` | Timezone-aware contractual expiry timestamp. |
| `ttm` | Non-negative time to maturity in years. State the day-count convention; the simulator uses elapsed seconds / 365 days. |
| `contract_size` | Units of underlying represented by one contract. |
| `discount` | Discount factor from `exchange_time` to `expiry`, not a rate. |

Adapters should populate all columns and use `NaN` for unavailable numeric observations. Zero has
economic meaning and must not be used as a generic missing-data marker.

## Minimal validation

```python
from option_chain_analytics import SliceColumn, generate_simulated_options_data

options_data = generate_simulated_options_data()
required = [column.value for column in SliceColumn]
assert list(options_data.chain_ts.columns) == required
assert options_data.chain_ts['exchange_time'].dt.tz is not None
assert options_data.chain_ts['expiry'].dt.tz is not None
assert (options_data.chain_ts['expiry'] > options_data.chain_ts['exchange_time']).all()
```

Do not infer spot returns from a forward series. A provider without independent spot observations
should return a missing `spot_data['close']` unless a caller explicitly opts into a labelled proxy
for display only.
