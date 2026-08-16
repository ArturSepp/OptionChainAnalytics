# Data sources and access boundaries

OCA normalises feeds but does not grant data rights. Empirical datasets remain outside the
repository until their redistribution terms are reviewed.

Install only the integration required by the study, for example
`pip install "option-chain-analytics[cboe]"`. The available extras are `cboe`, `deribit`, `yahoo`,
`ccxt`, `bloomberg`, and `fitters`; `all` installs every optional integration.

| Source path | Underlyings / local coverage | Current OCA status | Public replication use |
|---|---|---|---|
| Deterministic simulation | `SYNTH`; two observations and three expiries | Supported and release-gating | Yes; generated locally, no download. |
| CBOE fitted chains | SPX: 2015-01-02–2023-11-08; VIX: 2015-01-02–2024-05-31 | `load_local_cboe_options_data` maps to `OptionsDataDFs` inputs | No files distributed; users must provide lawful local access. |
| Tardis hourly chains | BTC/ETH: 2019-03-30–2024-05-06 UTC on the maintainer's local archive | Supported by `DataSource.TARDIS_LOCAL` when required local companion series exist | No files distributed; provider terms apply. |
| Deribit snapshots | BTC/ETH: 2023-10-27–2024-02-13 UTC on the maintainer's local archive | Supported by `DataSource.DERIBIT_LOCAL`; live retrieval is provider-specific | Historical archive not distributed. |
| Yahoo snapshots | Several equity/ETF names; local aggregate snapshots around 2024-06-20 | Loader exists; an aligned independent spot output is incomplete | Suitable for demonstrations only after documenting retrieval time and alignment. |
| Bloomberg BVOL | SPX daily volatility surfaces: 2005-01-03–2024-06-17 locally | Input exists; option-price mapping and maturity rolling are TODO | Bloomberg access required; synthetic output must be labelled, not represented as observed prices. |

## CBOE conventions

The mapper interprets source `date` as 16:00 New York time and `exdate` as 16:15 New York time,
then stores timezone-aware timestamps. Source `dte`, `impl_fw`, `impl_df`, and `mid_vols` become
time to maturity, forward, discount factor, and mark implied volatility. The files do not contain
an independent spot series. Bid/ask implied volatilities are always inferred from the source
bid/ask prices using those contemporaneous pricing inputs.

Use `build_local_cboe_options_cache(ticker='SPX')` and
`build_local_cboe_options_cache(ticker='VIX')` once to materialize normalized Zstandard-compressed
Parquet files. Parquet is used instead of CSV because it preserves timezone-aware timestamps and
numeric dtypes, supports predicate filtering by observation time, and is substantially smaller and
faster for these multi-million-row panels. The loader prefers a valid cache automatically. Each
file contains an OCA schema version and source size/modification fingerprint; a changed source or
schema requires an explicit `overwrite=True` rebuild.

For research returns, supply a separately licensed and time-aligned spot series. The
`is_use_front_forward_as_spot=True` switch is a visualisation-only proxy and should be identified as
such in figures and tables.

## Local layout

Set `OCA_DATA_PATH` to the local data root. With no override, a source checkout uses ignored
`data/`. Never commit raw vendor files, credentials, machine-specific paths, or generated empirical
outputs. Replication instructions should name the provider, access date, transformations, coverage,
timezone, and missing-data policy even when the underlying file cannot be redistributed.
