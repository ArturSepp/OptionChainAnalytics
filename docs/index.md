# OptionChainAnalytics documentation

OptionChainAnalytics is a source-neutral data-container layer for point-in-time option research.
It normalises heterogeneous feeds into `OptionsDataDFs`, reconstructs complete chains at an exact
historical observation time, and exposes expiry, strike, volatility, roll, and portfolio queries.

The fastest route is [first success](first_success.md). It is deterministic, offline, and requires
no provider account. Before mapping empirical data, read the [schema contract](schema.md),
[point-in-time rules](point_in_time.md), and [data-source boundaries](data_sources.md).

The repository's [supported examples](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/examples/README.md)
state the data prerequisite, network behavior, and output of every runnable script. Cache-first
SPY workflows make no request after the local ThetaData cache has been built.

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
