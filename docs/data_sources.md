---
myst:
  html_meta:
    description: >-
      Data sources for option-chain-analytics: raw and cache storage paths, loaders for CBOE
      SPX/VIX, Tardis and Deribit crypto, and ThetaData equity option data, provider conventions and
      data-rights boundaries.
---

# Data sources and access boundaries

*Author: [Artur Sepp](https://github.com/ArturSepp) / First recorded: [2026-08-16](https://github.com/ArturSepp/OptionChainAnalytics/commit/312512765e5dcdd44fdd90103a26eac6837640ff)*

Implemented in [option-chain-analytics](https://github.com/ArturSepp/OptionChainAnalytics).
Software citation: [CITATION.cff](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/CITATION.cff).

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
| ThetaData ETF EOD backtests (up to 400 DTE) | `$OCA_CACHE_PATH/thetadata_options_backtest/` when configured to the shared cache root | `load_thetadata_eod_cache` | loader returns `OptionsDataDFs` |
| Deterministic fixture | no storage; generated in memory | `generate_simulated_options_data` | loader returns `OptionsDataDFs` |

Bloomberg BVOL surfaces, derived ATM/skew CSVs, and any retained Yahoo files are not
`OptionsDataDFs` sources. They must not be passed through a legacy or inferred adapter. The
workstation-local ignored `data/README.md` records physical paths, observed coverage, file sizes,
and gaps. The extended ThetaData archives use the same monthly option and spot layout under
`<ticker>_400d/`. A directory with the `_pilot` suffix contains a limited-period sample.

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
| ThetaData synchronized ETF quotes | SPY, HYG, TLT and GLD | [Cutoff snapshot example](#synchronized-thetadata-etf-snapshots) writes research Parquet with quote and session evidence | Requires entitled ThetaData access. |
| Bloomberg FX broker mids | EUR/USD at 1M, 2M, 3M, 6M and 1Y | [FX smile reconstruction](#fx-broker-smiles) produces five strike and mid-IV pairs per expiry | Run the synthetic example below or replay an entitled local snapshot. |
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
These are fixed dataset-mapping clocks, without an early-close holiday calendar. They are
not a universal schedule for AM-settled SPX or every SPXW expiration. Cboe's
[SPX specifications](https://www.cboe.com/tradable-products/sp-500/spx-options/spx-specifications)
distinguish the contract types and early-close exceptions.

Prices remain in index points. `usd_multiplier=1` converts them to USD per underlying unit;
`contract_size=100` is separate. A 2.5-point premium therefore represents USD 250 per contract.
Apply contract size only when a contract value is required, not when comparing Black prices
with quoted premiums. Cboe specifies the 100 multiplier for both
[SPX](https://www.cboe.com/tradable-products/sp-500/spx-options/spx-specifications) and
[VIX](https://www.cboe.com/tradable-products/vix/vix-options/specifications/).

New CBOE caches record `oca_price_convention=index_points`. The reader also recognizes
`usd_per_contract` in existing schema-3 CBOE caches as a historical metadata mislabel;
those caches already contain index-point prices. All provider, product, analytics, schema
and available source-fingerprint checks still apply. Reading performs no price scaling
or cache rewrite. Other price labels are rejected; older readers may reject the corrected
label and need a package update.

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

## Synchronized ThetaData ETF snapshots

The 6.1.0 development checkout provides `examples/build_thetadata_synchronized_etf.py`
for SPY, HYG, TLT and GLD. It builds national best bid and offer (NBBO) snapshots for
each completed trading session at 15:55 New York time, or five minutes before an early
close. Naive provider timestamps are interpreted in New York time and stored in UTC.
Stock and option quotes are in USD per share.

Use `schedule.parquet` to identify the valuation cutoff and `sessions.parquet` to
check which dates have a usable stock quote and eligible option rows. Use
`quotes.parquet` to trace each option back to its source timestamp, age, exclusion
flags and independent stock midpoint. The cutoff is the time used to value the
snapshot. Component quotes can have different update times.

- Stock quotes come from the consolidated stock feed at or before the cutoff in the
  same session. When the timestamp represents the sample grid, the reported
  sample lag is available and the actual quote age remains missing.
- Option quote timestamps record actual updates. Future quotes, quotes from another
  session, duplicate identities and invalid or crossed markets fail eligibility.
  Zero option bids are retained and flagged. Eligibility alone does not establish
  a valid two-sided quote under [OCA quote diagnostics](quote_diagnostics.md).
  The default expiry limit is 460 calendar days. Set `--option-max-age` in seconds
  to require a maximum option quote age.
- Provider implied volatility (IV) and Greeks are optional diagnostics on a separate
  sample grid. Their underlying reference is compared with an independent stock
  sample at or before the reference time when available. Match status and timestamps
  remain separate from cutoff quote eligibility.

The output is a research quote panel with per-session and per-month audit records.
Use `load_thetadata_eod_cache` for the separate normalized EOD cache format that
returns `OptionsDataDFs`. The [examples guide](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/examples/README.md)
describes provider prerequisites, commands and resumable output layout.

## Adjusted XLF contracts

The 6.1.0 development checkout includes two helpers in
`option_chain_analytics.data.occ_xlf` for the 19 September 2016 Financial Select
Sector SPDR Fund distribution. Pass the original option ID and opening session to
`xlf_contract_at_session(contract, opened_on, session)`. A position opened before
the distribution moves from `XLF` to `XLF1` on the effective session, with its
expiry, strike and right unchanged. The same rule maps `1XLF` and `2XLF` to their
adjusted roots. A new standard-root position retains its original ID.

`xlf1_intrinsic_value` returns USD per contract using the deliverable of 100 XLF
shares, 13 XLRE shares and the verified cash in lieu for the fractional XLRE share.
Pass contemporaneous unadjusted prices for both funds and the final official cash
amount. The strike and quoted premium retain their 100 multiplier. See the
[Options Clearing Corporation (OCC) adjustment memo #39575](https://www.miaxglobal.com/sites/default/files/alert-files/XLF_Distribution_39575.pdf).

For example, using synthetic prices and a synthetic cash amount, a call struck
at USD 22 has USD 115 of intrinsic value per contract:

```python
from option_chain_analytics.data.occ_xlf import xlf1_intrinsic_value

assert xlf1_intrinsic_value(
    strike=22.0, option_type="C", xlf_price=19.0, xlre_price=30.0, cash_in_lieu=25.0,
) == 115.0
```

For a quote-only ThetaData EOD cache, the top-level manifest can declare
`"spot_policy": "unavailable"`. The loader still requires matching option and
spot partitions. The spot frame must be empty for the loaded date range and the
option rows must have missing spot prices. This preserves the distinction
between the cached quotes and a separately sourced deliverable valuation.

## FX broker smiles

In the OCA 6.1.0 development checkout, `fx_smile_to_options_data(quotes)` accepts one or more
`FXSmileQuote` records for a single currency pair. Each record supplies dated
spot and forward rates in quote currency per base unit, the domestic delivery
discount factor, expiry time, ATM implied volatility, and the 10- and 25-delta
risk reversals and market strangles. Use decimal volatility throughout.
Observation and expiry must be timezone-aware. Time to expiry uses ACT/365F.

At each delta, the risk reversal equals call IV minus put IV. The market
strangle spread added to ATM gives one common IV. OCA finds the put and call
strikes at that common IV and prices both legs. It then holds these strikes
fixed and solves jointly for the two wing averages that reproduce both broker
premiums. The resulting smile passes through each wing at its own quoted delta
and through the supplied ATM. OCA interpolates IV linearly in log strike and
holds the nearest wing IV flat outside the pillars. Other interpolants can
produce different outright wing IVs from the same five broker quotes.

Select `forward` or `spot` delta, or their premium-adjusted variants
`forward_pa` and `spot_pa`. Spot delta uses the foreign factor implied by
the domestic factor times forward divided by spot. The premium-adjusted call
uses the higher-strike root. ATM may be spot, forward, or delta neutral. For
delta-neutral ATM, the strike is $F\exp(\sigma^2T/2)$ under unadjusted delta
and $F\exp(-\sigma^2T/2)$ under premium-adjusted delta.

The five rows per expiry carry `fx_pillar`, signed `fx_quote_delta`,
`market_strangle_strike` on each wing, the original inputs, and their source.
The standard `delta` column is the derivative of discounted premium with
respect to forward. `mark_price` is in quote currency per base unit.
`quote_to_usd` enables USD-valued analytics on crosses with two non-USD
currencies. Bid, ask, sizes and trading activity are missing. For a single
expiry, `panel.chain_ts.set_index("fx_pillar")[["strike", "mark_iv"]]` returns
the reconstructed grid in strike order.

### Reconstruct and check one expiry

This synthetic example uses a 13% ATM IV, a −3.1 percentage point 10-delta
risk reversal and a 1.4 percentage point 10-delta market strangle. The latter
prices both legs at 14.4% to establish the target premium.

```python
import numpy as np
import pandas as pd
from option_chain_analytics import FXSmileQuote, fx_smile_to_options_data

quote = FXSmileQuote(
    pair="EURUSD", value_time=pd.Timestamp("2025-01-02 15:00Z"),
    expiry=pd.Timestamp("2025-07-02 14:00Z"), spot=1.10, forward=1.12,
    discount=0.973, atm=0.13, rr10=-0.031, ms10=0.014, rr25=-0.016, ms25=0.005,
    delta_convention="spot", atm_convention="delta_neutral", source="synthetic",
)
panel = fx_smile_to_options_data([quote])
smile = panel.chain_ts.set_index("fx_pillar")
for level, rr in [(10, quote.rr10), (25, quote.rr25)]:
    assert np.isclose(smile.at[f"{level}C", "mark_iv"] - smile.at[f"{level}P", "mark_iv"], rr)
assert smile[["bid_iv", "ask_iv", "bid_price", "ask_price"]].isna().all().all()
```

To check the market strangle independently, take the two saved
`market_strangle_strike` values for each delta. Read the smile IV at each
strike using the log-strike interpolant, then price the put and call. Find the
single Black IV that reproduces their summed premium at those same strikes.
Subtract the ATM IV to recover `ms10` or `ms25`. On the five-tenor EUR/USD
snapshot retrieved on 25 November 2026 at 00:08:57 UTC, the maximum absolute
errors were $1.31\times10^{-17}$ or less for the risk reversals and
$1.68\times10^{-15}$ or less for the market strangles, in decimal IV.
The offline round-trip tests in `tests/test_fx_smile.py` also check the quoted
wing deltas across all four delta and three ATM conventions.

### Bloomberg fetch and offline replay

The [examples guide](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/examples/README.md)
lists `examples/fx_smile_bloomberg.py`, which requests
EUR/USD 1M, 2M, 3M, 6M and 1Y mids together and saves the raw response under
`$OCA_DATA_PATH/fx_smile/` (default `data/fx_smile/`). From the OCA checkout,
fetch with the Bloomberg extra and a connected terminal, then replay offline.

```bash
python examples/fx_smile_bloomberg.py --fetch
python examples/fx_smile_bloomberg.py --snapshot <saved-snapshot.csv>
```

The example interprets Bloomberg BFY mids as broker market strangles and uses
unadjusted spot delta, delta-neutral ATM and a 10 a.m. New York cut for all five
tenors. The one-year smile uses Bloomberg's `1Y` volatility tickers and its
`EURUSD12M Curncy` forward. Forward points use the vendor scale and maturity.
The derived CSV labels each pillar with `fx_tenor` and `fx_pillar`. Earlier
two-tenor snapshots replay on their original grid. A flat SOFR ACT/360 rate approximates
the USD spot-to-delivery discount. Supply the applicable quoting conventions
and delivery discount curve for a desk valuation. The recorded source inputs
are distinct from the five reconstructed marks.

Replay writes `<snapshot-stem>_derived.csv` beside the source file. Each of
the 25 rows carries the expiry forward, delivery discount, strike, option type
and decimal `mark_iv`. Bloomberg's `PX_MID` is in volatility percentage
points for the smile tickers. The example divides these values by 100 and
converts forward points using `FWD_SCALE`. The observation time is the UTC
retrieval time. Use the retained expiry and strike to match a fitted IV back
to its tenor and pillar. [StochVolModels calibration guide](https://stochvolmodels.readthedocs.io/en/latest/calibration.html)

## Local layout

Set `OCA_DATA_PATH` for raw provider inputs and `OCA_CACHE_PATH` for normalized reusable chains.
With no overrides, a source checkout uses ignored `data/` and `resources/`. Never commit raw vendor
files, normalized caches, credentials, machine-specific paths, or generated empirical outputs.
Replication instructions should name the provider, access date, transformations, coverage,
timezone, and missing-data policy even when the underlying file cannot be redistributed.
