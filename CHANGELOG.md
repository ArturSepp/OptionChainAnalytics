# Changelog

All notable public changes to OptionChainAnalytics are recorded here.

## 2.0.0 - 2026-08-16

### Added

- `generate_simulated_options_data`, a deterministic offline `OptionsDataDFs` fixture for tests,
  examples, and documentation.
- A release-gating `examples/first_success.py` workflow and task-oriented Sphinx documentation.
- SPX/VIX Vlad fitted-chain mapping to the native option-panel schema.

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
