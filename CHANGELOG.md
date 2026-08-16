# Changelog

All notable public changes to OptionChainAnalytics are recorded here.

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
