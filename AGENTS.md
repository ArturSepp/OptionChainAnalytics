# AGENTS.md

Guidance for AI coding agents working in the **OptionChainAnalytics** repository.

## Project overview

`option-chain-analytics` provides point-in-time option-chain containers, provider-feed
normalisation, historical reconstruction, queries, and visualisation for quantitative research.
The central contract is one long-form `OptionsDataDFs` panel that can reconstruct an auditable
`SlicesChain` at a requested observation time. Provider access, stochastic-volatility models,
strategy backtests, and proprietary datasets remain outside this package.

Distribution name `option-chain-analytics`; import name `option_chain_analytics`. Licensed MIT
(`LICENSE`). Empirical datasets are licensed separately and are not part of the distribution.

## Ecosystem position

This package is part of the open-source Python stack maintained at
[github.com/ArturSepp](https://github.com/ArturSepp). Before implementing anything non-trivial,
check whether it already belongs in one of these:

| Package | Repository | Purpose |
|---|---|---|
| `qis` | QuantInvestStrats | Time-series analytics, schedules, reporting, and visualisation |
| `option-chain-analytics` | OptionChainAnalytics | Option-feed normalisation and point-in-time chain reconstruction |
| `vanilla-option-pricers` | VanillaOptionPricers | Vanilla prices, Greeks, and implied-volatility inversion |
| `stochvolmodels` | StochVolModels | Stochastic-volatility pricing, simulation, and calibration |
| `bbg-fetch` | BloombergFetch | Bloomberg data retrieval |
| `optimalportfolios` | OptimalPortfolios | Portfolio construction and backtesting |
| `factorlasso` | factorlasso | Sparse factor models and covariance estimation |
| `trendfollowing` | TrendFollowingSystems | Trend-following theory and replication |
| `goal-based-allocation` | GoalBasedAllocation | Dynamic allocation under regime-switching jump-diffusions |

OCA consumes `qis` and `vanilla-option-pricers`. `bbg-fetch` is an optional provider integration.
StochVolModels consumes OCA only through its optional experiment adapter, and the private
SigmaStrats backtester consumes OCA as its data layer. This direction is deliberate: **OCA never
imports StochVolModels or SigmaStrats**. Do not vendor or copy code between repositories; put a
capability in the package that owns it.

## Repository layout

```
src/option_chain_analytics/
  __init__.py              stable package-root exports
  chain_ts.py              OptionsDataDFs and point-in-time observation panels
  option_chain.py          expiry slices, SlicesChain, schema enums, and chain queries
  chain_loader_from_ts.py  reconstruction and scheduled-chain helpers
  ts_loaders.py            local/provider adapters and normalized CBOE cache support
  data/                    simulated data and optional provider modules
  fitters/                 option-surface fitters
  utils/                   maturity rolls, numerics, forwards, and payoffs
  visuals/                 chain reports and plots
tests/                     offline and optional-integration tests
examples/                  repository-only runnable examples
docs/                      Sphinx documentation
tools/                     distribution verification
```

The root `data/`, `agents/`, and `outputs/` directories are ignored. They contain local datasets,
agent work products, and generated research output and are excluded from distributions.

## Commands

```bash
pip install -e ".[dev]"
pytest -q
ruff check src tests examples tools docs/conf.py
python examples/first_success.py
sphinx-build -W -b html docs docs/_build/html
python -m build
python tools/verify_distribution.py dist
```

Install `.[vlad]` for Feather/Parquet CBOE data, or the relevant provider extra (`deribit`,
`yahoo`, `ccxt`, `bloomberg`, `fitters`). Supported Python is >= 3.10; CI runs tests and lint on
Python 3.10–3.14. CI also builds the documentation and verifies both wheel and source distribution.

## Conventions

- Tests are named `test_*.py` and live in the top-level `tests/` directory.
- Line length is 120 (`ruff`, rules `E`, `F`, `W`, `I`). Narrow per-file ignores preserve legacy
  provider/numerical code; do not expand them for new code.
- `SliceColumn` is the canonical option-observation schema. Adapters return every schema column in
  enum order, plus aligned `spot_data` and `ticker` suitable for `OptionsDataDFs(**result)`.
- Observation and expiry timestamps are timezone-aware; normalized timestamps are UTC.
- Volatility is decimal (`0.20` means 20%); time to maturity is in years. Forward, discount,
  contract-size, USD-multiplier, and price conventions must be explicit.
- Provider-only dependencies are imported lazily or inside provider paths. Importing OCA's core or
  using simulated data must not require Bloomberg, Yahoo, Deribit, or other optional services.
- Runnable examples live under root `examples/`, use the public API where possible, and do not
  require private data unless clearly labelled as local diagnostics.
- Public docstrings use NumPy style. Provider transformations document source timezones, price
  units, and any inferred fields.

## Point-in-time contract

- Exact observation selection is the reconstruction default.
- Scheduled studies may request `time_selection='previous'`; it selects the latest observation at
  or before the requested timestamp and must never select a future row.
- When `previous` selects an earlier observation, the reconstructed chain stores the actual feed
  timestamp as `value_time`, not the requested schedule time.
- Time indexes are sorted before selection. A request before the first observation returns no
  chain rather than borrowing the first future observation.
- Never use a full-sample statistic, backward fill, nearest-neighbour selection, or an end-of-day
  value that was unavailable at the requested time inside a point-in-time path.

## CBOE/Vlad data and cache contract

- `load_local_vlad_options_data` is the source-specific adapter for the local SPX/VIX fitted-chain
  files. The historical loader name is retained for compatibility.
- Bid/ask IV is always inferred from each row's bid/ask price using its contemporaneous forward,
  discount factor, and time to maturity. There is no switch that permits partially normalized
  CBOE data.
- Source `date` is interpreted as 16:00 New York time and `exdate` as 16:15 New York time, matching
  the documented source convention. Both become UTC internally.
- `build_local_cboe_options_cache` writes one Zstandard-compressed Parquet file per underlying:
  `spx_options_oca.parquet` and `vix_options_oca.parquet`. Do not combine the histories or replace
  them with CSV.
- Cache files embed the OCA format/schema version, ticker, creation time, and source-file size and
  modification fingerprint. A stale or incompatible cache is rejected; do not silently accept it.
- Cache creation streams Arrow record batches, writes to a unique temporary file, and atomically
  replaces the target only after success. Preserve this property for large SPX histories.
- Non-invertible quotes produce `NaN` IV under the pricer's bounds policy; one pathological quote
  must not abort normalization of the full history.

## Paths and data licensing

`OCA_DATA_PATH` points to the local data root containing provider subdirectories such as
`vlad_vols/`; `OCA_OUTPUT_PATH` points to generated output. With no override, a source checkout
uses ignored root `data/` and `outputs/` directories. Do not introduce absolute machine paths.

- Never commit vendor data, CBOE/Vlad source files, normalized caches, credentials, database
  dumps, calibration output, or generated figures.
- Public tests, examples, and visualisations use `generate_simulated_options_data` unless a
  dataset's redistribution terms have been reviewed and recorded.
- Dataset presence on a maintainer workstation is not redistribution permission. Software MIT
  licensing does not license empirical data.
- Do not reintroduce the obsolete AWS PostgreSQL trial-account integration. Local files are the
  empirical research boundary unless a separate provider integration is explicitly approved.

## Constraints — do not do these

- Do not add stochastic-volatility models, calibration objectives, or Monte Carlo simulation;
  those belong in StochVolModels.
- Do not add strategy construction, execution, P&L, or portfolio backtests; those belong in
  SigmaStrats or the relevant strategy package.
- Do not duplicate Black-Scholes/Bachelier prices, Greeks, or implied-volatility solvers; use
  `vanilla-option-pricers`.
- Do not make optional provider packages hard dependencies without approval.
- Do not change timestamp, discount, multiplier, volatility, or option-type conventions merely to
  accommodate one downstream consumer. Resolve convention disagreements at the owning boundary.
- Do not change `NearestStrikeOnGrid.BELOW`/`ABOVE`: BELOW selects the lower grid value and ABOVE
  selects the upper grid value.
- Do not treat Bloomberg BVOL surfaces as observed option prices. Synthetic option mapping remains
  a TODO until maturity rolling and price-generation conventions are implemented and labelled.
- Do not regenerate, weaken, or bypass cache fingerprints to make a stale cache load.

## Repository-specific agent artifacts

By maintainer direction, all OCA roadmaps, execution plans, audits, and reports live in the ignored
`agents/` directory. This repository-specific rule overrides the generic roadmap location inside
the generated shared-agent block below; do not edit that generated block directly.

<!-- ===== SHARED AGENT CORE (consumer variant) — begin =====
     Generated from SHARED_AGENT_CORE.md in the maintainer's project knowledge. Do not hand-edit
     between these markers — propose the change to the maintainer instead. Variants: builder
     (qis) / consumer / standalone. Last synced 2026-08-16, agent core v1.4. -->

## Domain invariants

- **No look-ahead in any reconstruction or scheduled research path.** An observation is usable
  only at or after its feed timestamp. Point-in-time selection, maturity rolling, and alignment to
  spot data preserve this boundary.
- Conventions are stated, never implied: timezone, volatility quotation, price units, discount,
  rate/dividend treatment, multiplier, and annualisation. One convention per concept across the
  stack — if two packages disagree, report the bug rather than silently adapting both.
- Normalization is deterministic: identical source rows, package versions, and configuration
  produce identical schema-aligned observations.

## Use the stack before you write it

OCA consumes `qis` for general time-series/visualisation utilities and
`vanilla-option-pricers` for vanilla pricing and IV inversion. Reimplementing an exported
capability is a defect, not a convenience.

- Check the installed export surface before calling or recreating a symbol. For example:
  `python -c "import vanilla_option_pricers as v; print([n for n in dir(v) if 'implied' in n])"`.
- If a required symbol is absent, say so. Never invent a sibling-package function or keyword.
- OCA is an upstream data layer for StochVolModels and SigmaStrats. Never import either downstream
  package into OCA or move their calibration/backtest logic here.
- If reimplementation is genuinely unavoidable, name the rejected stack symbol and reason in a
  comment immediately above the definition.

## Verification loop

- Plan → patch → verify. Name the verification command and result when proposing a patch.
- Prove a defect test fails before trusting that it passes: reintroduce the defect, observe the
  failure, then restore the correction.
- A second pass is mandatory where code can be numerically or temporally wrong while running
  clean. Point-in-time changes need boundary tests proving no future selection. IV or pricing
  changes need comparison to `vanilla-option-pricers` or parity/reference prices. Cache changes
  need a real Feather-to-Parquet round trip, filtered read, fingerprint rejection, and row-count
  check where local data is available.

## Escalation and scope

- Stop and propose before proceeding when a change would exceed roughly five files, alter a public
  signature, change the cache schema, or touch a numerical normalization path.
- Never change numerical results, timestamp policy, cache format, random seeds, or simulated values
  unless the change is the request.
- A public-signature change carries a `CHANGELOG.md` entry and a version bump in the same change.
  Removing a keyword accepted through `**kwargs` is a silent break; treat it as breaking.
- Do not refactor beyond the requested scope. Propose the wider change before implementing it.

## Concurrent sessions

More than one agent or session may work on this checkout at the same time, and local cache builds
may also be running.

- Re-read a file from disk immediately before editing it. Never replace a file using stale content.
- Prefer minimal anchored edits. If the current content differs from the expected version, stop and
  reconcile rather than overwriting another session's work.
- Do not delete or overwrite a cache unless the exact target is resolved and an explicit rebuild
  was requested. Cache builders use unique temporary files for concurrency safety.

## Roadmap execution

Feature roadmaps normally live at the repository root as `ROADMAP_<feature>.md`. In OCA, the
repository-specific rule above overrides this: roadmaps and execution reports live in ignored
`agents/`. A stage is complete only when its stated verification command passes; its out-of-scope
list is binding.

<!-- ===== SHARED AGENT CORE — end ===== -->

## Release checklist

1. `version` in `pyproject.toml`.
2. `CHANGELOG.md` entry with added/changed/fixed/removed classification and public symbols named.
3. `version` and `date-released` in `CITATION.cff`.
4. Software BibTeX in `README.md`, if it pins a version.
5. `pytest -q`, Ruff, offline first-success, warning-free docs, distribution build, and
   `tools/verify_distribution.py` all pass.

Then commit, tag `v<version>`, publish the wheel/source distribution, and create the matching
GitHub Release. Do not bump versions as part of unrelated work, and do not publish without the
maintainer explicitly asking for a release.

## Known issues and compatibility surfaces

- `create_chain_from_from_options_dfs` contains a historical doubled `from` in its public name.
  Preserve it unless a separately approved deprecation/migration introduces a corrected alias.
- `load_local_vlad_options_data` retains the source-specific historical name while the normalized
  public cache builder is `build_local_cboe_options_cache`.
- The CBOE cache path requires the `vlad` extra (`pyarrow`); cache round-trip tests skip when that
  optional dependency is absent from the test environment.
- Bloomberg BVOL data is a volatility surface input, not yet an OCA option-chain source; synthetic
  prices and maturity rolling remain deliberately unimplemented.
