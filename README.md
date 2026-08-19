# OptionChainAnalytics

OptionChainAnalytics provides point-in-time option-chain containers, feed normalisation,
chain reconstruction, queries, and visualisation in Python for quantitative research.

It is the data-container layer: provider credentials and data rights, pricing models, portfolio
backtests, and proprietary datasets remain separate. Pricing and implied-volatility inversion are delegated to
[`vanilla-option-pricers`](https://github.com/ArturSepp/VanillaOptionPricers); generic time-series
and plotting utilities come from [`qis`](https://github.com/ArturSepp/QuantInvestStrats).

## Install

OptionChainAnalytics requires Python 3.10 or newer. CI covers Python 3.10 through 3.14.

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
| `cboe` | Local Arrow/Feather CBOE fitted-chain files |
| `deribit` | Deribit HTTP collection helpers |
| `ccxt` | CCXT market-data integration |
| `bloomberg` | Bloomberg retrieval through `bbg-fetch` |
| `thetadata` | ThetaData national EOD equity/ETF option reports (Python 3.12+) |
| `docs`, `dev`, `all` | Documentation, contributor tooling, or every optional integration |

For example, `pip install "option-chain-analytics[cboe]"` installs the CBOE file dependency without
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

Observation and expiry timestamps are timezone-aware. Exact lookup is the reconstruction default;
scheduled studies can explicitly select the latest previous observation, but never a later one.
Volatilities are decimals (`0.20` means 20%), time to maturity is in years, and each adapter must
preserve and document its price/multiplier convention.

Provider adapters own feed-specific choices such as report alignment, rate symbols, settlement
timestamps, product scope, and admissible bounds. Reusable numerical kernels live separately under
`option_chain_analytics.fitters`; the call-put parity fitter has no provider or optional-solver
dependency. Black-Scholes analytics remain delegated to `vanilla-option-pricers`.

## Empirical feeds

Local adapters cover Deribit/Tardis crypto histories and SPX/VIX CBOE fitted-chain files. These
datasets are not distributed. Set `OCA_DATA_PATH` to an ignored local data root; generated output
uses `OCA_OUTPUT_PATH`. CBOE files can be mapped with:

```python
from option_chain_analytics import OptionsDataDFs
from option_chain_analytics.ts_loaders import load_local_cboe_options_data

options_data = OptionsDataDFs(
    **load_local_cboe_options_data(
        ticker='SPX',
        start='2023-01-03',
        end='2023-01-03',
    )
)
```

The CBOE mapper always infers bid/ask implied volatilities from the source bid/ask prices using
the contemporaneous forward, discount factor, and time to maturity. This keeps every CBOE-backed
`OptionsDataDFs` instance on the same complete schema.

For repeated empirical studies, build one normalized Parquet cache per underlying after installing
the `cboe` extra:

```python
from option_chain_analytics.ts_loaders import build_local_cboe_options_cache

build_local_cboe_options_cache(ticker='SPX')
build_local_cboe_options_cache(ticker='VIX')
```

This creates ignored `cboe_options/spx_options_oca.parquet` and
`cboe_options/vix_options_oca.parquet` files. The normal loader uses a valid cache automatically and
still accepts `start`/`end` filters. OCA embeds its cache schema and source-file fingerprint in each
Parquet file and rejects stale caches. Use `overwrite=True` to rebuild deliberately.

CBOE data supplies implied forwards but no independent spot series. Pass `spot_data`, or use
`is_use_front_forward_as_spot=True` only for visualisation; a forward proxy is not a valid spot
return series for backtesting.

ThetaData EOD equity/ETF reports can be fetched directly into the same container after installing
the optional client:

```bash
pip install "option-chain-analytics[thetadata]"
python examples/fetch_thetadata_eod.py
python examples/fetch_thetadata_eod.py --live --ticker AAPL \
    --value-date 2026-07-24 --expiration 2026-08-21 --metric atm
python examples/fetch_thetadata_eod.py --live --ticker MSFT \
    --value-date 2026-07-24 --expiration 2026-08-21 --metric skew --delta 0.25
```

For reusable research history, build resumable monthly Parquet partitions once:

```bash
python examples/build_thetadata_eod_cache.py --ticker SPY --start-date 2023-06-01
```

The callable API supports bounded reads, so a monthly analysis does not scan the full cache:

```python
from option_chain_analytics import load_thetadata_eod_cache

spy_july = load_thetadata_eod_cache(
    'data/thetadata_options/spy',
    start_date='2026-07-01',
    end_date='2026-07-31',
)
```

The same example exposes a regular function for IDE, notebook, or application use:

```python
from examples.fetch_thetadata_eod import display_thetadata_eod_metrics

result = display_thetadata_eod_metrics(
    ticker='AAPL',
    value_date='2026-07-24',
    expiration='2026-08-21',
    metric='atm',  # 'atm', 'skew', or 'both'
    delta=0.25,
    is_live=True,
)
print(result['atm_vol'])
```

To load the local SPY prototype, reconstruct an exact chain at every EOD timestamp, and plot
rolling ATM volatility or 25-delta skew:

```bash
python examples/fetch_thetadata_atm_timeseries.py --metric atm --output spy_atm_vol.png
python examples/fetch_thetadata_atm_timeseries.py --metric skew --output spy_skew.png
```

Pass `--live --ticker AAPL --start-date ... --end-date ...` to fetch instead of reading a cache.

The live callable form returns the OCA history object, reconstructed chain dictionary, ATM data
frame, and Matplotlib figure:

```python
from examples.fetch_thetadata_atm_timeseries import fetch_and_plot_thetadata_atm_vols

options_data, chains, atm_data, figure = fetch_and_plot_thetadata_atm_vols(
    ticker='AAPL',
    start_date='2026-07-20',
    end_date='2026-08-14',
    min_dte=7,
    max_dte=60,
    days_before_roll=7,
    output_path='aapl_atm_vol.png',
)
```

For skew, call `fetch_and_plot_thetadata_skew` from the same module. The returned `atm_data` contains
both `atm_vol` and `skew`, plus the selected `expiration` and actual `dte`. OCA defines delta skew as
`(call IV - put IV) / log(call strike / put strike)`; the plot displays 100 times this decimal slope
as volatility points per unit log-strike.

The first command is synthetic, deterministic, credential-free, and does not contact ThetaData.
Live mode delegates authentication to the
official ThetaData client, including its `THETADATA_API_KEY` and credentials-file mechanisms. The
adapter records the provider's actual EOD report time, joins only an underlying report available at
or before that time, preserves both calls and puts, fetches ThetaData SOFR EOD by default to anchor
the discount factor, and robustly infers forwards from parity. Set `rate_symbol=None` for a parity-only
fit. Every bid, mark, and ask IV and every mark Greek is computed by `vanilla-option-pricers`.
Use `--metric atm`, `--metric skew`, or the default `--metric both`. ATM volatility averages call
and put mark IV at the nearest forward strike. Delta skew is OCA's call-minus-put volatility slope
over log-strike distance at the requested absolute delta. The adapter deliberately excludes index
options with product-specific or AM settlement conventions.

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
