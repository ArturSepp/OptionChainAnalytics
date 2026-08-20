# Supported examples

Every example is runnable with deterministic data, a standardized local cache, or explicit
provider access. Vendor data and credentials are never included in the repository.

| Example | Data required | Network | Result |
|---|---|---:|---|
| `first_success.py` | None; generated deterministic panel | No | Reconstructed chain, ATM volatility, and roll selection |
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
