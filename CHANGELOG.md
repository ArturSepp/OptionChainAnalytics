# Changelog

All notable public changes to OptionChainAnalytics are recorded here.

## [Unreleased]

## [5.2.0] - 2026-08-24

### Added

- `ChainTs.load_price_data` returns a selected and optionally resampled underlying series from
  the `spot_data` panel linked to the same option-chain history.

### Removed

- Retired the contributor-facing `dev` extra in favor of PEP 735 dependency groups:
  `test` for pytest and Python 3.10 TOML support, and `lint` for Ruff. The user-facing
  provider, documentation, and aggregate extras remain available.

## [5.1.0] - 2026-08-22

### Changed

- Component development diagnostics now live beside their owning modules in source-only
  `run_local/*_run.py` namespace folders and use the `Locals` / `run_local(local=...)` contract.
- Runnable examples use the same dispatcher names while remaining broader repository workflows;
  automated pytest modules remain centralized under `tests/`.
- Wheel and source-distribution verification reject development runners.

## [5.0.0] - 2026-08-20

### Added

- `create_chain_at_time` is the canonical exact/previous point-in-time reconstruction function.
- `option_chain_analytics.option_data`, `.conventions`, and `.reconstruction` provide explicit
  homes for normalized containers, shared conventions, and chain reconstruction.
- `examples/build_thetadata_eod_cache.py` now exposes `create_thetadata_options_data`, which builds
  or resumes monthly ThetaData partitions and returns the complete history as one `OptionsDataDFs`.

### Changed

- `create_chain_timeseries` now accepts the clearly named `options_data` input and delegates each
  scheduled observation to `create_chain_at_time` without changing the no-look-ahead policy.
- Provider-independent call-put parity forward/discount inference moved from the one-file
  `fitters` package to `option_chain_analytics.utils.forward_discount`.
- Provider loading is split by responsibility across `data.cache`, `data.cboe`, `data.tardis`,
  `data.deribit`, and `data.loaders`; package-root `DataSource` and `ts_data_loader_wrapper` remain
  unchanged.
- The provider modules now document their data ownership, timestamp, quote-unit, cache, and
  optional-dependency boundaries in detail. The README includes an installed-package ThetaData
  workflow from resumable cache construction through rolling ATM/skew plots and an exact-date
  multi-expiry chain report.
- All tracked runnable examples now use the maintainer-standard `LocalTests` enum and
  `run_local_test(local_test=...)` dispatcher entry point.
- Normalized CBOE, Tardis EOD, and ThetaData caches now resolve through `OCA_CACHE_PATH`, defaulting
  to the ignored repository `resources/` directory. `OCA_DATA_PATH` remains the separate root for
  raw provider archives, while custom CBOE/Tardis directories retain co-located caches.
- The root and examples READMEs now provide the authoritative six-example inventory, including
  each workflow's data prerequisite, network behavior, output, and cache-first command sequence.

### Fixed

- ATM call/put and volatility queries now fall back to the nearest valid quote on each option side
  when a provider reports asymmetric strike grids, avoiding failures in otherwise valid ThetaData
  histories.

### Removed

- Removed the canonical and historical compatibility module paths named `chain_loader_from_ts.py`,
  `chain_ts.py`, and `config.py`.
- Removed `create_chain_from_from_options_dfs` and its doubled-`from` public name.
- Removed the research helpers `generate_atm_vols_skew` and `generate_vol_delta_ts`; rolled
  empirical analytics now live in their downstream SVM examples and SigmaStrats research code.
- Removed the CCXT exchange adapter and integration surface; exchange-specific spot and funding
  retrieval now belongs to downstream research applications rather than OCA.
- Removed the maintainer-only combined local-cache CLI from tracked public examples; the ignored
  `prop/` copy remains available for private CBOE and Tardis archives.
- Removed the now-empty `option_chain_analytics.fitters` module path without a compatibility shim.
- Removed the monolithic `option_chain_analytics.ts_loaders` module path; provider-specific imports
  now use their owning `option_chain_analytics.data` modules.
- Removed the legacy approximate LogSV smile fitter and its embedded OCA report/demo module after
  migrating the provider-independent analytics to `stochvolmodels.fitters` and updating
  SigmaStrats to import the synthetic grid-price helper from SVM.
- Removed obsolete Bloomberg-surface, legacy crypto-volatility/funding, option-portfolio bump, and
  duplicate CBOE-cache examples. The retained examples now use deterministic data, standardized
  local caches, or explicit provider access.

## [4.0.0] - 2026-08-19

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

## [3.0.0] - 2026-08-16

### Changed

- Renamed the complete local SPX/VIX integration to CBOE terminology: the optional extra is now
  `cboe`, the provider enum is `DataSource.CBOE_LOCAL`, and the loader and mapper are
  `load_local_cboe_options_data` and `map_cboe_options_data`.
- Local files now resolve under `cboe_options/`, normalized caches identify themselves as
  `option_chain_analytics.cboe.normalized`, and source attributes use `cboe_options`.

### Removed

- Removed the pre-3.0 source-label API, extra, constants, cache identifier, and directory name.
  Existing normalized SPX/VIX caches must be rebuilt once to receive the CBOE cache metadata.

## [2.0.1] - 2026-08-16

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

## [2.0.0] - 2026-08-16

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
