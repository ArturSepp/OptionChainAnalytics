---
myst:
  html_meta:
    description: >-
      Documentation for option-chain-analytics: point-in-time option-chain containers in Python,
      feed normalisation for CBOE, Tardis, Deribit and ThetaData data, historical chain
      reconstruction and chain queries.
---

# option-chain-analytics

*Author: [Artur Sepp](https://github.com/ArturSepp) / First recorded: [2026-08-16](https://github.com/ArturSepp/OptionChainAnalytics/commit/312512765e5dcdd44fdd90103a26eac6837640ff)*

Implemented in [option-chain-analytics](https://github.com/ArturSepp/OptionChainAnalytics).
Software citation: [CITATION.cff](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/CITATION.cff).

<a id="optionchainanalytics-documentation"></a>

Point-in-time option-chain containers, feed normalisation, reconstruction, and queries for
quantitative research.

The fastest route is [first success](first_success.md). It is deterministic, offline, and requires
no provider account. Before mapping empirical data, read the [schema contract](schema.md),
[point-in-time rules](point_in_time.md), and [data-source boundaries](data_sources.md).

The repository's [supported
examples](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/examples/README.md)
state the data prerequisite, network behavior, and output of every runnable script. Cache-first
SPY workflows make no request after the local ThetaData cache has been built.

For observed-data diagnostics, start with [quote quality and exact-time parity](quote_diagnostics.md).
Its [workflow table](quote_diagnostics.md#choose-a-diagnostic-workflow) distinguishes packaged
APIs from repository-only research helpers. Continue with
[retrospective event freshness](quote_diagnostics.md#retrospective-event-freshness-and-asynchrony)
for calibration-frozen event-age/asynchrony evidence and
[parity attribution](quote_diagnostics.md#parity-attribution-and-recovery-from-original-evidence)
for missing-pair causes and recovery from original records. Fitted-surface consistency,
sensitivity and longitudinal replay belong to
[StochVolModels](https://github.com/ArturSepp/StochVolModels/blob/main/docs/surface_diagnostics.md).

```{toctree}
:maxdepth: 2
:caption: User guide

first_success
schema
point_in_time
quote_diagnostics
queries
data_sources
comparison
```
