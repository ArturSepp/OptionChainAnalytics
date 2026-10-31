# option-chain-analytics

*Author: [Artur Sepp](https://github.com/ArturSepp) / First recorded: [2023-02-03](https://github.com/ArturSepp/OptionChainAnalytics/commit/72d2e05805d09deca91bfbfe94425f2e46130c79)*

Implemented in [option-chain-analytics](https://github.com/ArturSepp/OptionChainAnalytics).
Software citation: [CITATION.cff](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/CITATION.cff).

**Point-in-time option-chain containers, feed normalisation, reconstruction, and queries for quantitative research**

OCA is the data-container layer: provider credentials and data rights, stochastic-volatility
models, strategy backtests, and proprietary datasets remain separate.

**Install:** `pip install option-chain-analytics` · **Import:** `option_chain_analytics` · **Status:** Beta

[![PyPI](https://img.shields.io/pypi/v/option-chain-analytics?style=flat-square)](https://pypi.org/project/option-chain-analytics/)
[![Python](https://img.shields.io/pypi/pyversions/option-chain-analytics?style=flat-square)](https://pypi.org/project/option-chain-analytics/)
[![CI](https://github.com/ArturSepp/OptionChainAnalytics/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ArturSepp/OptionChainAnalytics/actions/workflows/ci.yml)
[![Docs](https://readthedocs.org/projects/optionchainanalytics/badge/?version=latest)](https://optionchainanalytics.readthedocs.io/en/latest/)
[![License](https://img.shields.io/github/license/ArturSepp/OptionChainAnalytics.svg?style=flat-square)](LICENSE)
[![Downloads](https://static.pepy.tech/badge/option-chain-analytics)](https://pepy.tech/project/option-chain-analytics)
[![Monthly](https://static.pepy.tech/badge/option-chain-analytics/month)](https://pepy.tech/project/option-chain-analytics)

**Documentation:** [optionchainanalytics.readthedocs.io](https://optionchainanalytics.readthedocs.io/en/latest/) ·
[schema contract](docs/schema.md) · [point-in-time reconstruction](docs/point_in_time.md) ·
[data-source guide](docs/data_sources.md) · [examples guide](examples/README.md)

---

## Why option-chain-analytics

Provider feeds disagree on schemas, timestamps, identifiers, units, and available fields, and a
scheduled research path that reads them directly can silently select future data. OCA normalises
those feeds into one long-form `OptionsDataDFs` panel, then reconstructs an auditable
`SlicesChain` at an exact observation time or the latest explicitly requested prior observation.

### Key differentiators

- **One schema for every feed.** `SliceColumn` defines the common option-feed schema — source
  time, contract, forward, discount factor, strike, expiry, quote, implied volatility, Greeks,
  volume, and open interest — and every adapter (simulated, CBOE, Deribit/Tardis, ThetaData,
  Bloomberg) lands on it; see the [schema contract](docs/schema.md).
- **Point-in-time by contract.** Observation and expiry timestamps are timezone-aware; exact
  lookup is the reconstruction default, and scheduled studies can explicitly select the latest
  previous observation but never a later one; see [point-in-time reconstruction](docs/point_in_time.md).
- **Stated units.** Volatilities are decimals (`0.20` means 20%), time to maturity is in years,
  and each adapter must preserve and document its price/multiplier convention.
- **Analytics delegated, not duplicated.** Every bid, mark, and ask implied volatility and every
  mark Greek is computed by `vanilla-option-pricers`; the call-put parity utility under
  `option_chain_analytics.utils` has no provider or optional-solver dependency.
- **A credential-free path.** The deterministic simulated-data path exercises the same containers
  and queries as the optional empirical adapters.

### When to use it — and when not

Use `option-chain-analytics` to normalise option feeds into one panel, to reconstruct a chain at
an exact historical observation time, to query one expiry for ATM, delta-strike, volatility,
open-interest and execution-price values, to run quote-quality and parity diagnostics, and to
build resumable local caches for repeated empirical studies.

OCA is the data-container layer: provider credentials and data rights, stochastic-volatility
models (see [`stochvolmodels`](https://github.com/ArturSepp/StochVolModels)), strategy
backtests, and proprietary datasets remain separate. Vanilla pricing is
[`vanilla-option-pricers`](https://github.com/ArturSepp/VanillaOptionPricers); portfolio
analytics and reporting are [`qis`](https://github.com/ArturSepp/QuantInvestStrats).

## Installation

OptionChainAnalytics 6.0 and later requires Python 3.11 or newer. CI covers Python 3.11 through 3.14.
Python 3.10 users must remain on the 5.3.x release line.

Install the published package:

```bash
pip install option-chain-analytics
```

Provider-specific integrations are optional:

| Extra | Capability |
|---|---|
| `cboe` | Local Arrow/Feather CBOE fitted-chain files |
| `deribit` | Deribit HTTP collection helpers |
| `bloomberg` | Bloomberg retrieval through `bbg-fetch` |
| `thetadata` | ThetaData national EOD equity/ETF option reports (Python 3.12+) |
| `docs`, `all` | Documentation, or every optional integration |

For example, `pip install "option-chain-analytics[cboe]"` installs the CBOE file dependency without
installing unrelated network providers. Contributor test and lint tools live in the locked `test`
and `lint` dependency groups rather than a published `dev` extra; see [Testing](#testing).

Empirical datasets are not distributed. `OCA_DATA_PATH` holds raw provider archives,
`OCA_CACHE_PATH` holds normalised reusable chains, and `OCA_OUTPUT_PATH` holds generated
reports; their source-checkout defaults are the ignored `data/`, `resources/`, and `outputs/`
directories. The [data catalogue](docs/data_sources.md#canonical-data-catalogue-and-storage)
defines every supported provider directory, cache filename, and loader.

## Table of contents

1. [Why option-chain-analytics](#why-option-chain-analytics)
2. [Installation](#installation)
3. [Statement of need](#statement-of-need)
4. [Overview](#overview)
5. [Five-minute quickstart](#five-minute-quickstart)
6. [Examples](#examples)
7. [Testing](#testing)
8. [Changelog](#changelog)
9. [Feedback & contributing](#feedback-contributing)
10. [Citation](#citation)
11. [Ecosystem](#ecosystem)
12. [License](#license)
13. [Disclaimer](#disclaimer)

## Statement of need

Empirical option research needs a public, auditable input layer: a chain reconstructed at a
stated observation time from a stated provider record, with stated units and no look-ahead, so
that a replication can start from the same object the study used. OCA provides that layer.
Strategy logic and the QF-paper backtests remain in SigmaStrats, and a public example is not
expected to reproduce results computed from a private production dataset exactly. Dataset
licences and access terms are separate from the software licence. No research paper is
implemented in this package; OCA is upstream of `stochvolmodels`, whose paper replications
consume OCA chains through its optional research workflow.

## Overview

The installable package lives under `src/option_chain_analytics/`; repository-only scripts live in
`examples/`. Provider adapters own feed-specific choices such as report alignment, rate symbols,
settlement timestamps, product scope, and admissible bounds; reusable numerical kernels live
separately under `option_chain_analytics.utils`. Component development diagnostics live beside
their implementation in `src/option_chain_analytics/**/run_local/*_run.py`, expose `Locals` and
`run_local(local=...)`, and are excluded from distributions (the `run_local` folders use implicit
namespace-package support and contain no `__init__.py`). Raw datasets, normalised caches, agent
reports, and generated outputs live in ignored `data/`, `resources/`, `agents/`, and `outputs/`
directories.

Data model:

- `OptionsDataDFs` holds an option-observation panel (`chain_ts`) plus an aligned spot-price frame.
- `SlicesChain` reconstructs all available expiries at one exact observation time.
- `ExpirySlice` provides call/put, ATM, delta-strike, volatility, open-interest, and execution-price
  queries for one expiry.
- `SliceColumn` defines the common option-feed schema, including source time, contract, forward,
  discount factor, strike, expiry, quote, implied volatility, Greeks, volume, and open interest.

### Analytics at a glance

| Area | What the package computes |
|---|---|
| Normalisation | Provider feeds (deterministic simulator, local CBOE fitted-chain files, Deribit/Tardis crypto histories, ThetaData national EOD reports, Bloomberg through `bbg-fetch`) → one long-form `OptionsDataDFs` panel on the `SliceColumn` schema; the CBOE mapper infers bid/ask implied volatilities from source bid/ask prices with the contemporaneous forward, discount factor and time to maturity |
| Reconstruction | `create_chain_at_time` → `SlicesChain` at an exact observation time, or the latest explicitly requested prior observation, never a later one; every provider report retains its actual timestamp |
| Queries | `ExpirySlice` call/put, ATM strike and volatility, delta-strike, volatility, open-interest and execution-price queries; weekly roll maturity selection; see [queries](docs/queries.md) |
| Diagnostics | Quote-quality, parity and source-row diagnostics on synthetic or empirical data, exact-pair parity attribution and recovery from original records; see [quote diagnostics](docs/quote_diagnostics.md) |
| Caches | Normalised Parquet caches per underlying (`build_local_cboe_options_cache`, `build_thetadata_eod_cache` / `load_thetadata_eod_cache` with resumable monthly partitions, schema and source-file fingerprints, stale-cache rejection); standardized local SPX, VIX, BTC and ETH cache construction |
| Reports | Cache-first ATM/skew time-series plots and multi-expiry PDF chain reports (`run_chain_report`) |

## Five-minute quickstart

The authoritative offline repository example constructs a deterministic Black-Scholes-Merton
option panel, reconstructs a historical chain, queries its front-expiry ATM strike and volatility,
and selects a weekly roll maturity. The `examples/` directory is not included in the wheel, so run
this from a source clone:

```bash
git clone https://github.com/ArturSepp/OptionChainAnalytics.git
cd OptionChainAnalytics
python examples/first_success.py
```

Expected evidence:

```text
ticker=SYNTH
observation_times=2
contracts_at_first_time=30
expiries=['12Jan2024', '19Jan2024', '16Feb2024']
first_expiry_atm=100.00, vol=0.2057
weekly_roll_expiries=['12Jan2024']
```

See [`examples/first_success.py`](examples/first_success.py) for the executable source. The
documentation includes that file directly, so the tutorial cannot drift into a second
implementation.

## Examples

### Highlighted examples

**Local CBOE fitted-chain files** (the `cboe` extra):

```python
from option_chain_analytics import OptionsDataDFs
from option_chain_analytics.data.cboe import load_local_cboe_options_data

options_data = OptionsDataDFs(
    **load_local_cboe_options_data(
        ticker='SPX',
        start='2023-01-03',
        end='2023-01-03',
    )
)
```

For repeated empirical studies, build one normalised Parquet cache per underlying with
`build_local_cboe_options_cache(ticker='SPX')`; the normal loader uses a valid cache
automatically and still accepts `start`/`end` filters, and OCA rejects stale caches. CBOE data
supplies implied forwards but no independent spot series: pass `spot_data`, or use
`is_use_front_forward_as_spot=True` only for visualisation; a forward proxy is not a valid spot
return series for backtesting.

**ThetaData EOD cache, reconstruction and report** (the `thetadata` extra; the official client
reads `THETADATA_API_KEY`, and credentials and raw provider responses are never written to OCA's
normalised cache):

```python
import pandas as pd

from option_chain_analytics import (
    build_thetadata_eod_cache, create_chain_at_time, load_thetadata_eod_cache,
)

cache_root = build_thetadata_eod_cache(
    ticker='NVDA',
    start_date='2023-06-01',
    min_dte=0,
    max_dte=60,
    strike_range=20,
)
nvda_july = load_thetadata_eod_cache(cache_root, start_date='2026-07-01', end_date='2026-07-31')

# Every provider report retains its actual timestamp; reconstruct the chain exactly at one of them
value_time = nvda_july.get_timeindex()[-1]
chain = create_chain_at_time(nvda_july, value_time)
print('value_time:', chain.value_time)
print('expiries:', list(chain.expiry_slices))
print('contracts:', len(chain.options_df))
```

The builder requests one month at a time and checkpoints each completed partition, so an
interrupted request can be rerun safely; monthly Parquet files are only the resumable physical
layout and the loader returns one continuous `OptionsDataDFs`. Index options with
product-specific or AM settlement conventions are deliberately outside this adapter. The adapter
records the provider's actual EOD report time, joins only an underlying report available at or
before that time, and preserves both calls and puts; direct snapshot and time-series loads
retrieve ThetaData SOFR EOD by default to anchor the discount factor and then infer forwards from
parity (`rate_symbol=None` for a parity-only fit), while the partitioned cache builder uses the
parity-only policy. The equivalent repository commands:

```bash
python examples/build_thetadata_eod_cache.py --ticker NVDA --start-date 2023-06-01
python examples/run_chain_report.py --ticker NVDA --date 2026-07-17 --output nvda_chain_report.pdf
```

### Runnable examples

The [examples guide](examples/README.md) lists every script, its required data, whether it makes a
network request, and its output. Removed research prototypes are not retained as runnable
examples.

- [`first_success.py`](examples/first_success.py) — generated deterministic panel; reconstructed
  chain, ATM volatility, and roll selection. No network.
- [`quote_diagnostics.py`](examples/quote_diagnostics.py) — generated panel with explicit
  injected defects; quote quality, parity, source-row exclusions and optional diagnostic figures.
- [`retrospective_freshness.py`](examples/retrospective_freshness.py) and
  [`parity_attribution.py`](examples/parity_attribution.py) — repository-only
  calibration-frozen event-age/asynchrony policy, and exact-pair parity attribution and recovery
  from original records, on generated data.
- [`fetch_thetadata_eod.py`](examples/fetch_thetadata_eod.py) — a single-expiry example;
  synthetic, deterministic and credential-free without `--live`, ATM volatility and/or 25-delta
  skew for one expiry with it.
- [`build_thetadata_eod_cache.py`](examples/build_thetadata_eod_cache.py),
  [`fetch_thetadata_atm_timeseries.py`](examples/fetch_thetadata_atm_timeseries.py),
  [`run_chain_report.py`](examples/run_chain_report.py) — resumable monthly EOD partitions,
  cache-first rolling ATM-volatility or skew plots, and the multi-expiry PDF chain report.

## Testing

```bash
uv sync --locked --group test
uv run --no-sync pytest -q
uv run --locked --only-group lint ruff check .
```

Automated checks use `tests/test_*.py` and need no provider credentials; the credential-free
simulated-data path exercises the same containers and queries as the optional empirical
adapters. The documentation and distribution checks from a source checkout are:

```bash
uv sync --locked --extra docs
uv run --no-sync python -m sphinx -E -W --keep-going -b html docs docs/_build/html
uv build --sdist --clear --out-dir dist
uv build --wheel dist/*.tar.gz --out-dir dist
uv run --no-project python tools/verify_distribution.py dist
```

## Changelog

Release history is maintained in [CHANGELOG.md](CHANGELOG.md).

## Feedback & contributing <a name="feedback-contributing"></a>

- **Bug:** [report a reproducible bug](https://github.com/ArturSepp/OptionChainAnalytics/issues/new?template=bug_report.yml), including the package version, Python/platform, provider or simulated-data path, timestamps, and expected versus actual result.
- **Feature:** [request a feature](https://github.com/ArturSepp/OptionChainAnalytics/issues/new?template=feature_request.yml), explaining which field, provider, or normalisation workflow is missing, the current workaround, and the smallest useful API.
- **Question or methodology:** search or open an [issue](https://github.com/ArturSepp/OptionChainAnalytics/issues) and name the adapter, schema column, or point-in-time rule involved.
- **Contribution:** read [CONTRIBUTING.md](CONTRIBUTING.md) for the data-licensing boundary, development commands, point-in-time rules, and pull-request guidance.

## Citation

Machine-readable citation metadata is provided in [`CITATION.cff`](CITATION.cff).

A copyable software citation is:

```bibtex
@software{sepp2026optionchainanalytics,
  title={option-chain-analytics: Point-in-time option-chain containers, feed normalisation, reconstruction, and queries for quantitative research},
  author={Sepp, Artur},
  year={2026},
  version={6.0.1},
  url={https://github.com/ArturSepp/OptionChainAnalytics}
}
```

## Ecosystem

This package is part of an open-source Python stack for quantitative finance. The
[ArturSepp profile](https://github.com/ArturSepp) is the canonical catalogue:

| Package | Purpose |
|---|---|
| [`qis`](https://github.com/ArturSepp/QuantInvestStrats) | Performance analytics, backtesting, and factsheet reporting |
| [`optimalportfolios`](https://github.com/ArturSepp/OptimalPortfolios) | Portfolio construction and rolling backtesting |
| [`factorlasso`](https://github.com/ArturSepp/factorlasso) | Sparse factor-model estimation |
| [`bbg-fetch`](https://github.com/ArturSepp/BloombergFetch) | Bloomberg data in pandas DataFrames |
| [`option-chain-analytics`](https://github.com/ArturSepp/OptionChainAnalytics) *(this package)* | Point-in-time option-chain data and queries |
| [`vanilla-option-pricers`](https://github.com/ArturSepp/VanillaOptionPricers) | Numba-vectorised BSM and Bachelier pricing |
| [`stochvolmodels`](https://github.com/ArturSepp/StochVolModels) | Stochastic-volatility pricing and calibration |
| [`trendfollowing`](https://github.com/ArturSepp/TrendFollowingSystems) | Closed-form trend-following analytics |
| [`privateassets`](https://github.com/ArturSepp/privateassets) | Multi-factor PME for private assets |
| [`goal-based-allocation`](https://github.com/ArturSepp/GoalBasedAllocation) | Goal-based allocation under regime-switching jump-diffusions |

OCA depends on `qis` for general time-series and visualisation utilities and on
`vanilla-option-pricers` for vanilla prices, Greeks, and implied-volatility inversion. `bbg-fetch`
is an optional provider integration. OCA remains upstream of `stochvolmodels`, which consumes it
only through the optional research workflow.

## License

The software is released under the [MIT License](LICENSE). The software licence does not grant
rights to any empirical dataset loaded through an optional provider integration.

## Disclaimer

`option-chain-analytics` is distributed FREE & WITHOUT ANY WARRANTY under the MIT License. See
[LICENSE](LICENSE) in the release for details. Use the routes in
[Feedback & contributing](#feedback-contributing) for bugs, feature requests and
methodology questions.
