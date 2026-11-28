# Supported examples

*Author: [Artur Sepp](https://github.com/ArturSepp) / First recorded: [2026-08-20](https://github.com/ArturSepp/OptionChainAnalytics/commit/71ef868d7111a99aa91147ef9cdd114d50d8605f)*

Implemented in [option-chain-analytics](https://github.com/ArturSepp/OptionChainAnalytics).
Software citation: [CITATION.cff](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/CITATION.cff).

Every example is runnable with deterministic data, a standardized local cache, or explicit
provider access. Run the scripts from the source checkout. For released usage, use the
[tagged 6.0.2 examples](https://github.com/ArturSepp/OptionChainAnalytics/tree/v6.0.2/examples)
with OCA 6.0.2. Rows marked **Development** use the 6.1.0 checkout. Vendor data and
credentials stay in private local storage.

| Example | Data required | Network | Result |
|---|---|---:|---|
| `first_success.py` | None; generated deterministic panel | No | Reconstructed chain, ATM volatility, and roll selection |
| `fx_smile_bloomberg.py` (Development) | Bloomberg Desktop or a saved EUR/USD snapshot | Only with `--fetch` | Five-pillar FX mid-IV grids for 1M, 2M, 3M, 6M and 1Y from broker ATM, risk reversals and market strangles |
| `quote_diagnostics.py` | None; generated panel with explicit injected defects | No | Quote quality, parity, source-row exclusions and optional diagnostic figure |
| `retrospective_freshness.py` | None; generated deterministic inventory | No | Repository-only calibration-frozen event-age/asynchrony policy, separate from receipt availability and exact-time parity |
| `parity_attribution.py` | None; generated panel with an asynchronous leg | No | Repository-only exact-pair attribution and recovery from original records; optional original-forward comparison remains separate from qualification |
| `fetch_thetadata_eod.py` | None by default; ThetaData account with `--live` | Optional | ATM volatility and/or 25-delta skew for one expiry |
| `build_thetadata_eod_cache.py` | Authenticated ThetaData account | Yes | Resumable monthly EOD partitions and one loaded `OptionsDataDFs` |
| `build_thetadata_synchronized_etf.py` (Development) | ThetaData Stocks Standard and Options Standard, or higher | Yes | Cutoff-aligned SPY, HYG, TLT and GLD stock and option NBBO parquet with audit manifests |
| `fetch_hyg_quote_audit.py` (Development) | ThetaData EOD access and a date CSV | Yes | Dated HYG option and stock reports for quote-quality comparison |
| `fetch_hyg_intraday_quotes.py` (Development) | Entitled ThetaData account and a New York session schedule | Yes | HYG option or stock NBBO snapshots with a file-hash manifest |
| `fetch_gld_study_inputs.py` (Development) | ThetaData EOD access and a date CSV | Yes | Dated GLD option and stock reports, with availability and file hashes |
| `fetch_thetadata_atm_timeseries.py` | Local ThetaData cache by default; `--live` is optional | No by default | Rolling ATM-volatility or skew plot |
| `run_chain_report.py` | Local ThetaData cache | No | Multi-expiry PDF chain report |

## Recommended sequence

Start with the credential-free workflow:

```bash
python examples/first_success.py
python examples/fetch_thetadata_eod.py
```

Build the SPY cache once, then reuse it without further requests:

```bash
python examples/build_thetadata_eod_cache.py --ticker SPY --start-date 2023-06-01
python examples/fetch_thetadata_atm_timeseries.py --metric atm --output spy_atm.png
python examples/fetch_thetadata_atm_timeseries.py --metric skew --output spy_skew.png
python examples/run_chain_report.py --date 2026-07-17 --output spy_chain_report.pdf
```

The cache builder is also a regular Python function. Monthly files are only its resumable storage
format; the returned value is one continuous research object:

```python
from examples.build_thetadata_eod_cache import create_thetadata_options_data

tlt_options = create_thetadata_options_data(
    ticker='TLT',
    start_date='2023-06-01',
    end_date='2023-06-30',
)
print(len(tlt_options.get_timeindex()))
```

The default cache root is `$OCA_CACHE_PATH/thetadata_options/<ticker>/`, or the ignored repository
`resources/thetadata_options/<ticker>/` directory when `OCA_CACHE_PATH` is unset. Use
`--cache-root` to select another cache explicitly. `OCA_DATA_PATH` remains the separate root for
raw provider archives.

Provider datasets, generated Parquet files, plots, and reports remain local ignored artifacts.

## Synchronized ETF snapshots with ThetaData

Use the synchronized example when an ETF share quote and all contracts in its
daily chain need a common valuation time. The schedule uses 15:55 New York
time or five minutes before an early close. Run the example with Python 3.12
or newer and the `thetadata` extra. Configure the ThetaData client credentials
and set `OCA_CACHE_PATH` to your private cache root before running.

```powershell
$cache = Join-Path $env:OCA_CACHE_PATH 'thetadata_synchronized_eod/v1/etf_pilot'
python examples/build_thetadata_synchronized_etf.py `
  --tickers HYG TLT GLD --start 2024-11-27 --end 2024-11-29 --output $cache
```

The output contains the original request parameters and snapshots under `raw/`,
and `quotes.parquet` and `sessions.parquet` under `panel/<TICKER>/<YYYY-MM>/`.
Read the eligibility and age flags in the quote file and use the session file
to check missing stock or option snapshots. The coverage manifest summarizes
completed months, request failures and matched provider diagnostics. Stocks
use the independent consolidated `utp_cta` NBBO midpoint. A stock timestamp at
the sample grid leaves the actual quote age unknown. Earlier subminute report
timestamps carry a measured age. The option timestamp records its update. The default maturity
limit is 460 calendar days with all strikes. Carry, implied volatility and
sensitivities can be rebuilt by the downstream study from the synchronized
quote panel.

SPY's full-strike requests can take longer. To request a narrower chain and
check the strike range again against the independent midpoint, use
`--tickers SPY --request-strike-range 20 --strike-range 20`. The maturity limit
is controlled separately by `--max-dte`.

Repeat the same command to resume. Use `--repair-contracts` to retry malformed
expiry responses by right and strike. Provide `--eod-root` to compare with
existing end-of-day inputs. Choose a new output folder when changing the date
range, cutoff configuration or eligibility settings.

## HYG and GLD quote studies

These scripts save raw reports for downstream quote-quality studies. Run them with
Python 3.12 or newer, the `thetadata` extra and access to the requested endpoints.
Set `OCA_DATA_PATH` to a private raw-data directory before using the commands below.

- EOD inputs use a CSV with a `date` column in `YYYY-MM-DD` format. The option
  requests ask for all expiries through 460 calendar days. An EOD report's
  `created` timestamp identifies the report. Actual last quote-update timestamps
  require the at-time feed.
- HYG at-time inputs use `date,time_of_day` with one row per session, for example
  `2024-11-29,12:55:00`. Use New York time and supply the appropriate cutoff for
  each session, including early closes. Run once per asset in separate output
  directories. The script checks contract identity and quote timestamps. It
  preserves the raw quotes for later quality and maturity filtering.
- Use `availability.csv` to review completed and failed requests and
  `manifest.json` to trace saved files. Keep the selection and acquisition
  settings fixed when resuming into the same directory.

```powershell
$raw = $env:OCA_DATA_PATH
python examples/fetch_hyg_quote_audit.py --selection dates.csv --output "$raw/hyg_eod"
python examples/fetch_hyg_intraday_quotes.py --selection sessions.csv --asset options --output "$raw/hyg_options"
python examples/fetch_hyg_intraday_quotes.py --selection sessions.csv --asset stock --output "$raw/hyg_stock"
python -m examples.fetch_gld_study_inputs --selection dates.csv --output "$raw/gld_eod"
```
