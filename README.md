# OptionChainAnalytics

OptionChainAnalytics provides point-in-time option-chain containers, feed normalisation,
chain reconstruction, queries, and visualisation in Python for quantitative research.

It is the data-container layer: provider retrieval, pricing models, portfolio backtests, and
proprietary datasets remain separate. Pricing and implied-volatility inversion are delegated to
[`vanilla-option-pricers`](https://github.com/ArturSepp/VanillaOptionPricers); generic time-series
and plotting utilities come from [`qis`](https://github.com/ArturSepp/QuantInvestStrats).

## Install

OptionChainAnalytics requires Python 3.14 or newer.

Install the published package:

```bash
pip install option-chain-analytics
```

For development from a clone:

```bash
pip install -e .
```

Provider-specific integrations are optional:

| Extra | Capability |
|---|---|
| `vlad` | Local Arrow/Feather Vlad fitted-chain files |
| `deribit` | Deribit HTTP collection helpers |
| `yahoo` | Yahoo snapshots and the fitter used by that adapter |
| `ccxt` | CCXT market-data integration |
| `bloomberg` | Bloomberg retrieval through `bbg-fetch` |
| `fitters` | CVXPY-based quote fitting |
| `docs`, `dev`, `all` | Documentation, contributor tooling, or every optional integration |

For example, `pip install "option-chain-analytics[vlad]"` installs the Vlad file dependency without
installing unrelated network providers.

## First success: no data or credentials

The authoritative offline example constructs a deterministic Black-Scholes-Merton option panel,
reconstructs a historical chain, queries its front-expiry ATM strike and volatility, and selects a
weekly roll maturity:

```bash
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

## Data model

- `OptionsDataDFs` holds an option-observation panel (`chain_ts`) plus an aligned spot-price frame.
- `SlicesChain` reconstructs all available expiries at one exact observation time.
- `ExpirySlice` provides call/put, ATM, delta-strike, volatility, open-interest, and execution-price
  queries for one expiry.
- `SliceColumn` defines the common option-feed schema, including source time, contract, forward,
  discount factor, strike, expiry, quote, implied volatility, Greeks, volume, and open interest.

Observation and expiry timestamps are timezone-aware. A point-in-time reconstruction performs an
exact timestamp lookup; it does not silently use a later observation. Volatilities are decimals
(`0.20` means 20%), time to maturity is in years, and each adapter must preserve and document its
price/multiplier convention.

## Empirical feeds

Local adapters cover Deribit/Tardis crypto histories and SPX/VIX Vlad fitted-chain files. These
datasets are not distributed. Set `OCA_DATA_PATH` to an ignored local data root; generated output
uses `OCA_OUTPUT_PATH`. Vlad files can be mapped with:

```python
from option_chain_analytics import OptionsDataDFs
from option_chain_analytics.ts_loaders import load_local_vlad_options_data

options_data = OptionsDataDFs(
    **load_local_vlad_options_data(
        ticker='SPX',
        start='2023-01-03',
        end='2023-01-03',
        is_compute_bid_ask_iv=True,
    )
)
```

Vlad data supplies implied forwards but no independent spot series. Pass `spot_data`, or use
`is_use_front_forward_as_spot=True` only for visualisation; a forward proxy is not a valid spot
return series for backtesting.

The Bloomberg BVOL-to-synthetic-option mapping remains a TODO: it must define maturity rolling and
price generation before BVOL surfaces can be represented as option panels.

## Documentation and development

Start with the [documentation site](https://artursepp.github.io/OptionChainAnalytics/), then read the
[schema contract](https://artursepp.github.io/OptionChainAnalytics/schema.html),
[point-in-time reconstruction](https://artursepp.github.io/OptionChainAnalytics/point_in_time.html),
and [data-source guide](https://artursepp.github.io/OptionChainAnalytics/data_sources.html).

```bash
pytest -q
ruff check src tests examples tools docs/conf.py
sphinx-build -W -b html docs docs/_build/html
python -m build
```

The installable package lives under `src/option_chain_analytics/`; repository-only scripts live in
`examples/`. Local datasets, agent reports, and generated outputs live in ignored `data/`, `agents/`,
and `outputs/` directories.

## Research and licensing boundary

OCA can provide a public, auditable input layer for empirical studies and replication. Strategy
logic and the QF-paper backtests remain in SigmaStrats, and a public example is not expected to
reproduce results computed from a private production dataset exactly.

The software is released under the [MIT License](LICENSE). Dataset licences and access terms are
separate from the software licence. Citation metadata is provided in [`CITATION.cff`](CITATION.cff),
and contribution guidance is provided in [`CONTRIBUTING.md`](CONTRIBUTING.md).
