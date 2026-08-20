# Data sources and access boundaries

OCA normalises feeds but does not grant data rights. Empirical datasets remain outside the
repository until their redistribution terms are reviewed.

## Canonical data catalogue and storage

Raw provider inputs and normalized option caches have separate roots. OCA resolves raw data from
`OCA_DATA_PATH` and normalized caches from `OCA_CACHE_PATH`; when unset, a source checkout uses its
ignored `data/` and `resources/` directories. Code must use
`option_chain_analytics.local_path.get_resource_path()` and `get_cache_path()` rather than embed a
workstation path.

```text
<OCA_DATA_PATH>/
├── cboe_options/
│   └── provider source files
├── tardis/                          # provider hourly source files
├── deribit/                         # provider snapshots and aggregate files
└── bbg_vols/                        # source surfaces, not option chains

<OCA_CACHE_PATH>/
├── cboe_options/
│   ├── spx_options_oca.parquet
│   └── vix_options_oca.parquet
├── tardis/
│   ├── btc_options_oca.parquet
│   └── eth_options_oca.parquet
└── thetadata_options/
    └── <ticker-lower>/
        ├── manifest.json
        ├── options/YYYY-MM.parquet
        └── spot/YYYY-MM.parquet
```

The following catalogue is the supported path from stored data to `OptionsDataDFs`:

| Data | Canonical storage path | Loader | Container construction |
|---|---|---|---|
| CBOE SPX/VIX EOD | `$OCA_CACHE_PATH/cboe_options/{spx,vix}_options_oca.parquet` | `load_local_cboe_options_data` | `OptionsDataDFs(**payload)` |
| Tardis BTC/ETH EOD | `$OCA_CACHE_PATH/tardis/{btc,eth}_options_oca.parquet` | `load_local_tardis_eod_options_data` | `OptionsDataDFs(**payload)` |
| Tardis BTC/ETH hourly | provider files under `$OCA_DATA_PATH/tardis/` | `DataSource.TARDIS_LOCAL` | `OptionsDataDFs(**payload)` |
| Deribit BTC/ETH snapshots | provider files under `$OCA_DATA_PATH/deribit/` | `DataSource.DERIBIT_LOCAL` | `OptionsDataDFs(**payload)` |
| ThetaData equity/ETF EOD | `$OCA_CACHE_PATH/thetadata_options/<ticker>/` | `load_thetadata_eod_cache` | loader returns `OptionsDataDFs` |
| Deterministic fixture | no storage; generated in memory | `generate_simulated_options_data` | loader returns `OptionsDataDFs` |

Bloomberg BVOL surfaces, derived ATM/skew CSVs, and any retained Yahoo files are not
`OptionsDataDFs` sources. They must not be passed through a legacy or inferred adapter. The
workstation-local ignored `data/README.md` records physical junction targets, observed coverage,
file sizes, and datasets retained only as source material.

To inspect the resolved root in any environment:

```python
from option_chain_analytics.local_path import get_cache_path, get_resource_path

print(get_resource_path())
print(get_cache_path())
```

Install only the integration required by the study, for example
`pip install "option-chain-analytics[cboe]"`. The available extras are `cboe`, `deribit`,
`bloomberg`, and `thetadata`; `all` installs every optional integration available for the
running Python version. The official ThetaData client requires Python 3.12 or newer.

| Source path | Underlyings / local coverage | Current OCA status | Public replication use |
|---|---|---|---|
| Deterministic simulation | `SYNTH`; two observations and three expiries | Supported and release-gating | Yes; generated locally, no download. |
| CBOE fitted chains | SPX: 2015-01-02–2023-11-08; VIX: 2015-01-02–2024-05-31 | `load_local_cboe_options_data` maps to `OptionsDataDFs` inputs | No files distributed; users must provide lawful local access. |
| Tardis hourly chains | BTC/ETH: 2019-03-30–2024-05-06 UTC on the maintainer's local archive | Hourly source through `DataSource.TARDIS_LOCAL`; exact 08:00 UTC EOD caches through `DataSource.TARDIS_EOD_LOCAL` | No files distributed; provider terms apply. |
| Deribit snapshots | BTC/ETH: 2023-10-27–2024-02-13 UTC on the maintainer's local archive | Supported by `DataSource.DERIBIT_LOCAL`; live retrieval is provider-specific | Historical archive not distributed. |
| ThetaData national EOD | US equity/ETF option roots available to the authenticated account | `DataSource.THETADATA_EOD` maps contract quotes and aligned stock EOD reports to `OptionsDataDFs` inputs | Provider subscription and data terms apply; no responses are distributed. |
| Bloomberg BVOL | SPX daily volatility surfaces: 2005-01-03–2024-06-17 locally | Input exists; option-price mapping and maturity rolling are TODO | Bloomberg access required; synthetic output must be labelled, not represented as observed prices. |

Only workflows listed in the
[`examples/README.md`](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/examples/README.md)
guide are maintained as runnable examples. In particular, OCA does not ship a Bloomberg BVOL
example until the synthetic-option mapping and maturity-roll policy are defined.

## CBOE conventions

The consolidated SPX dataset contains SPXW contracts and uses PM settlement at 16:00 New York
time. VIX/VIXW uses the morning Special Opening Quotation at 09:30 New York time; its last trading
day is normally the preceding business day. OCA recomputes expiry and time to maturity from these
product policies instead of preserving the legacy files' common 16:15 `dte` convention.

The legacy fitted `impl_fw`, `impl_df`, `mid_vols`, `delta`, and `vega` columns are not trusted by
the cache converter. For every observation/expiration, OCA replaces the old fitted mark with the
bid/ask midpoint, robustly refits forward and discount from call-put parity, and calculates mark,
bid, and ask implied volatilities plus mark delta and vega with `vanilla-option-pricers`. Expiries
without sufficient aligned call/put quotes are omitted. The files do not contain an independent
spot series.

Use `build_local_cboe_options_cache(ticker='SPX')` and
`build_local_cboe_options_cache(ticker='VIX')` once to materialize normalized Zstandard-compressed
Parquet files. Parquet is used instead of CSV because it preserves timezone-aware timestamps and
numeric dtypes, supports predicate filtering by observation time, and is substantially smaller and
faster for these multi-million-row panels. The loader prefers a valid cache automatically. Each
file contains an OCA schema version and source size/modification fingerprint; a changed source or
schema requires an explicit `overwrite=True` rebuild.

Build both reusable research caches from the consolidated local datasets through the public API:

```python
from option_chain_analytics.data.cboe import build_local_cboe_options_cache

for ticker in ('SPX', 'VIX'):
    build_local_cboe_options_cache(
        ticker=ticker,
        local_path='/path/to/cboe_options',
        overwrite=True,
    )
```

With the default provider directories, this writes `spx_options_oca.parquet` and
`vix_options_oca.parquet` under `$OCA_CACHE_PATH/cboe_options/`. A custom `--cboe-dir` retains the
previous co-located source/cache behavior. Cache metadata fingerprints the source and records the
OCA schema, settlement policy, and analytics policy. The default cache inputs are the consolidated
daily `spx_options.feather` and `vix_options.feather`. The much larger annual intraday archives are
deliberately not collapsed into these files; a future partitioned intraday cache can preserve their
full timestamp granularity.

For research returns, supply a separately licensed and time-aligned spot series. The
`is_use_front_forward_as_spot=True` switch is a visualisation-only proxy and should be identified as
such in figures and tables.

## Standardized local EOD caches

SPX, VIX, BTC, and ETH caches use the same physical Parquet schema: `contract`,
`underlying_index`, `mat_id`, and `optiontype` are Arrow strings; `exchange_time` and `expiry` are
nanosecond UTC timestamps; every other `SliceColumn` is `float64`. This deliberately converts CBOE
integer sizes/strikes and Tardis `float32` fields to one nullable numerical representation.

BTC and ETH are sampled from the hourly Tardis archive at exactly 08:00 UTC. Missing snapshots are
not replaced with earlier or later rows. Their inverse option prices remain in BTC/ETH units,
`usd_multiplier` is the expiry forward, `spot_price` is the exact-time Deribit index price, and the
legacy Tardis discount convention is one. The perpetual index is preferred for spot; when it is
absent, an exact-time `index_price` row from the option feed is used, never a value from another
timestamp. The source BTC/ETH histories cover 2019-03-30 08:00 UTC through 2024-05-05 08:00 UTC
after daily sampling.

Build or rebuild the standardized caches through their provider-specific public functions:

```python
from option_chain_analytics.data.cboe import build_local_cboe_options_cache
from option_chain_analytics.data.tardis import build_local_tardis_eod_options_cache

for ticker in ('SPX', 'VIX'):
    build_local_cboe_options_cache(
        ticker=ticker,
        local_path='/path/to/cboe_options',
        overwrite=True,
    )
for ticker in ('BTC', 'ETH'):
    build_local_tardis_eod_options_cache(
        ticker=ticker,
        local_path='/path/to/tardis',
        daily_hour_utc=8,
        overwrite=True,
    )
```

With default provider directories, the four files are written under
`$OCA_CACHE_PATH/{cboe_options,tardis}/`. Custom source directories retain co-located caches.
Metadata stores the common schema and dtype policy plus provider-specific timestamp, settlement,
analytics, price, and source-fingerprint policies. Use `load_local_tardis_eod_options_data` for
BTC/ETH; it returns the same `chain_ts`, `spot_data`, and `ticker` constructor payload as the CBOE
loader.

## ThetaData EOD conventions

Install `option-chain-analytics[thetadata]` on Python 3.12 or newer. The loader delegates
authentication to the official client; credentials and API keys are never stored by OCA. The
credential-free path in `examples/fetch_thetadata_eod.py` injects a deterministic client with the
same method contract and does not contact ThetaData, while `--live` uses the provider client and
requires the Theta Terminal/account.

For example, display AAPL ATM volatility for a specified historical report date and expiration:

```bash
python examples/fetch_thetadata_eod.py --live --ticker AAPL \
    --value-date 2026-07-24 --expiration 2026-08-21 --metric atm
```

Select `--metric skew --delta 0.25` for OCA's 25-delta call-minus-put volatility slope over
log-strike distance, or `--metric both` to print both values. The expiration is required because an
ATM volatility or skew is maturity-specific.

`load_thetadata_eod_options_data` fetches one report date and either explicit expirations or the
provider's filtered expiration listing. Its scope is US equity and ETF options. ThetaData's
date-only expiration is interpreted as 16:00 America/New_York and converted to UTC. Do not use the
adapter for SPX, VIX, or another index until that product's AM/PM settlement and expiry timestamp
are represented explicitly.

The mapper retains separate call and put contracts, USD bid/mid/ask prices, sizes, and report-period
volume. Live loaders request ThetaData's SOFR EOD history by default, convert the percentage rate to
a flat continuously compounded discount factor, and robustly infer the forward from joint call/put
quotes. Pass `rate_symbol=None` to infer both terms from parity, or pass a different supported rate
symbol. Parity fitting uses inverse-spread weights, Huber reweighting, and explicit discount bounds.
All bid, mark, and ask implied volatilities and mark Greeks come from `vanilla-option-pricers`.
Expiries without sufficient parity inputs are omitted instead of receiving a disguised spot proxy.
The option EOD endpoint does not supply open interest, so that field remains `NaN`.

The SOFR choice, point-in-time rate alignment, staleness limit, US-equity/ETF scope, expiry time,
and provider-level discount bounds belong to the ThetaData adapter. The reusable parity regression
is provider-neutral and lives in `option_chain_analytics.utils.forward_discount`.

Build resumable monthly cache partitions with:

```bash
python examples/build_thetadata_eod_cache.py --ticker SPY --start-date 2023-06-01
```

`load_thetadata_eod_cache(cache_root, start_date=..., end_date=...)` reads only overlapping
monthly partitions and returns the same `OptionsDataDFs` container as the live loaders. The
cache uses parity-only rate fitting consistently across the free history and remains ignored local
vendor data.

Reuse the cache for plots and a chain report without contacting ThetaData:

```bash
python examples/fetch_thetadata_atm_timeseries.py --metric atm --output spy_atm.png
python examples/fetch_thetadata_atm_timeseries.py --metric skew --output spy_skew.png
python examples/run_chain_report.py --date 2026-07-17 --output spy_chain_report.pdf
```

The option `created` field is the observation time. The underlying stock report keeps its own
timestamp and is joined to an option row only when it was available at or before the option report;
a later close is never backward-filled. Normalized metadata records the source, price convention,
expiry convention, and spot-alignment policy. Optional local Parquet caches contain normalized
responses and are never distributed by OCA.

## Local layout

Set `OCA_DATA_PATH` for raw provider inputs and `OCA_CACHE_PATH` for normalized reusable chains.
With no overrides, a source checkout uses ignored `data/` and `resources/`. Never commit raw vendor
files, normalized caches, credentials, machine-specific paths, or generated empirical outputs.
Replication instructions should name the provider, access date, transformations, coverage,
timezone, and missing-data policy even when the underlying file cannot be redistributed.
