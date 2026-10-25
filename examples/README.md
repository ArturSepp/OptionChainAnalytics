# Supported examples

*Author: [Artur Sepp](https://github.com/ArturSepp) / First recorded: [2026-08-20](https://github.com/ArturSepp/OptionChainAnalytics/commit/71ef868d7111a99aa91147ef9cdd114d50d8605f)*

Implemented in [option-chain-analytics](https://github.com/ArturSepp/OptionChainAnalytics).
Software citation: [CITATION.cff](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/CITATION.cff).

Every example is runnable with deterministic data, a standardized local cache, or explicit
provider access. Vendor data and credentials are never included in the repository.

| Example | Data required | Network | Result |
|---|---|---:|---|
| `first_success.py` | None; generated deterministic panel | No | Reconstructed chain, ATM volatility, and roll selection |
| `quote_diagnostics.py` | None; generated panel with explicit injected defects | No | Quote quality, parity, source-row exclusions and optional diagnostic figure |
| `retrospective_freshness.py` | None; generated deterministic inventory | No | Repository-only calibration-frozen event-age/asynchrony policy, separate from receipt availability and exact-time parity |
| `parity_attribution.py` | None; generated panel with an asynchronous leg | No | Repository-only exact-pair attribution and recovery from original records; optional original-forward comparison remains separate from qualification |
| `fetch_thetadata_eod.py` | None by default; ThetaData account with `--live` | Optional | ATM volatility and/or 25-delta skew for one expiry |
| `build_thetadata_eod_cache.py` | Authenticated ThetaData account | Yes | Resumable monthly EOD partitions and one loaded `OptionsDataDFs` |
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
