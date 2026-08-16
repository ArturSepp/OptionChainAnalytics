# OptionChainAnalytics documentation

OptionChainAnalytics is a source-neutral data-container layer for point-in-time option research.
It normalises heterogeneous feeds into `OptionsDataDFs`, reconstructs complete chains at an exact
historical observation time, and exposes expiry, strike, volatility, roll, and portfolio queries.

The fastest route is [first success](first_success.md). It is deterministic, offline, and requires
no provider account. Before mapping empirical data, read the [schema contract](schema.md),
[point-in-time rules](point_in_time.md), and [data-source boundaries](data_sources.md).

```{toctree}
:maxdepth: 2
:caption: User guide

first_success
schema
point_in_time
queries
data_sources
comparison
```
