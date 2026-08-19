# Changelog

All notable public changes to OptionChainAnalytics are recorded here.

## 4.0.0 - 2026-08-19

### Added

- `build_thetadata_eod_cache` and `load_thetadata_eod_cache` provide resumable monthly ThetaData
  EOD Parquet partitions in OCA's canonical schema, including bounded report-date loading for
  research workflows.
- ThetaData EOD loaders now retrieve the provider's `SOFR` history by default and use the latest
  point-in-time rate as a flat continuously compounded discount anchor. Pass `rate_symbol=None`
  to retain parity-only estimation, or select another supported ThetaData rate symbol.
- `DataSource.TARDIS_EOD_LOCAL`, `build_local_tardis_eod_options_cache`, and
  `load_local_tardis_eod_options_data` provide exact 08:00 UTC BTC/ETH daily caches from local
  hourly Tardis archives, including exact-time Deribit index prices and source fingerprints.
- `examples/build_local_options_caches.py` builds SPX, VIX, BTC, and ETH caches in one command.
- `DataSource.THETADATA_EOD`, `load_thetadata_eod_options_data`,
  `load_thetadata_eod_options_timeseries`, and `map_thetadata_eod_options_data` provide point-in-time
  normalization of ThetaData national EOD equity and ETF option reports.
- The optional `thetadata` integration extra and a credential-free deterministic example provide
  an opt-in authenticated live mode and selectable ATM-volatility or delta-skew output.
- A callable ThetaData EOD time-series example builds `OptionsDataDFs`, reconstructs exact
  point-in-time chains, extracts rolling ATM volatility and delta skew, and produces Matplotlib
  plots for either metric.

### Changed

- The ThetaData ATM/skew and chain-report examples now default to the local SPY cache; authenticated
  live history remains an explicit opt-in path.
- CBOE SPX and VIX cache conversion now replaces legacy fitted terms with robust parity forwards
  and discounts plus `vanilla-option-pricers` implied volatilities, delta, and vega. SPX is treated
  as PM-settled SPXW at 16:00 New York; VIX uses its 09:30 morning SOQ convention.
- Normalized local caches now use schema version 3 and one physical `SliceColumn` schema across
  SPX, VIX, BTC, and ETH: UTC timestamps, Arrow strings, and `float64` numerics. CBOE schema-2
  caches must be rebuilt explicitly; metadata records the shared dtype policy and provider-specific
  observation, settlement, analytics, price, and source-fingerprint policies.
- Call-put parity fitting now uses inverse-spread weights, Huber reweighting, enforced discount
  bounds, and an optional externally supplied discount factor. The provider-neutral implementation
  now lives in `option_chain_analytics.fitters.forward_discount`.
- ThetaData keeps provider policy in its adapter: SOFR selection, point-in-time report alignment,
  rate staleness, US-equity/ETF scope, expiry timestamp, and provider-level discount bounds.
- ThetaData implied volatilities and Greeks continue to use `vanilla-option-pricers` exclusively;
  provider IVs are not mixed into OCA's normalized analytics.
- ThetaData option reports preserve call/put contracts and raw bid/ask quotes while deriving
  forwards and discounts from call-put parity and implied volatilities and Greeks through
  `vanilla-option-pricers`.
- The optional ThetaData extra installs `python-dotenv`, which ThetaData 1.0.10 imports but does
  not declare in its wheel metadata.

### Fixed

- Chain reports now use current Matplotlib primitives for ATM annotations and open-interest
  legends instead of removed `qis` helpers, and support filtered single-strike slices.

### Removed

- Removed the unused and untested CVXPY quote fitter, the `fitters` optional extra, and CVXPY from
  the `all` extra. Generic parity fitting remains part of the core installation.
- Removed the incomplete Yahoo snapshot adapter, its public lazy export, the `yahoo` extra, and the
  `yfinance` dependency from `all`. The deterministic simulated-data and injected ThetaData-client
  examples remain the credential-free workflows.

## 3.0.0 - 2026-08-16

### Changed

- Renamed the complete local SPX/VIX integration to CBOE terminology: the optional extra is now
  `cboe`, the provider enum is `DataSource.CBOE_LOCAL`, and the loader and mapper are
  `load_local_cboe_options_data` and `map_cboe_options_data`.
- Local files now resolve under `cboe_options/`, normalized caches identify themselves as
  `option_chain_analytics.cboe.normalized`, and source attributes use `cboe_options`.

### Removed

- Removed the pre-3.0 source-label API, extra, constants, cache identifier, and directory name.
  Existing normalized SPX/VIX caches must be rebuilt once to receive the CBOE cache metadata.

## 2.0.1 - 2026-08-16

### Added

- `build_local_cboe_options_cache`, which streams source Feather batches into one validated,
  compressed normalized Parquet cache per SPX/VIX underlying.
- Root `AGENTS.md` guidance covering point-in-time, provider, cache, licensing, dependency, and
  release invariants for automated coding agents.

### Changed

- Restored support for Python 3.10 and newer, with CI across Python 3.10-3.14 and Python 3.10
  fallbacks in project and distribution metadata checks.
- CBOE normalisation now always derives bid/ask implied volatilities from source row prices using
  the contemporaneous forward, discount factor, and time to maturity.
- `load_local_cboe_options_data` now prefers validated per-underlying Parquet caches while retaining
  source parsing as the fallback and supporting filtered point-in-time loads.
- Point-in-time reconstruction now supports an explicit `previous` observation policy that can
  only select data at or before the requested timestamp; exact selection remains the default.

### Fixed

- Scheduled chain construction now records the actual selected observation time and cannot borrow
  a later observation when the requested schedule timestamp is absent.
- Non-invertible CBOE quotes now produce `NaN` bid/ask IV rather than aborting normalization of a
  complete cache build.

## 2.0.0 - 2026-08-16

### Added

- `generate_simulated_options_data`, a deterministic offline `OptionsDataDFs` fixture for tests,
  examples, and documentation.
- A release-gating `examples/first_success.py` workflow and task-oriented Sphinx documentation.
- SPX/VIX CBOE fitted-chain mapping to the native option-panel schema.

### Changed

- Adopted a `src/` package layout and moved repository-only scripts to root `examples/`.
- Raised the minimum supported Python version to 3.14.
- Consolidated package metadata in `pyproject.toml` and moved provider integrations to optional
  extras so the offline data-container workflow does not install unrelated feeds.
- Made the MIT licence explicit and added `CITATION.cff`.
- Made provider modules lazy under `option_chain_analytics.data` so optional feeds are not imported
  merely to use simulated data.
- Preserved the historical `option_chain_analytics.data.chain_ts`, `.config`, and
  `.chain_loader_from_ts` import paths as compatibility modules for downstream research code.
- Local data and output paths now default to ignored repository directories and support
  `OCA_DATA_PATH` and `OCA_OUTPUT_PATH` overrides.
- Corrected `NearestStrikeOnGrid.BELOW` and `ABOVE` to select the lower and upper grid values,
  respectively; downstream SigmaStrats usage was updated to retain intended behavior.

### Fixed

- Removed obsolete AWS PostgreSQL trial-account configuration and machine-specific settings.

### Removed

- Legacy `setup.py` and `requirements.txt` metadata duplicated by `pyproject.toml`.
