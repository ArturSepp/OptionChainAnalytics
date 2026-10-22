---
myst:
  html_meta:
    description: >-
      A deterministic, offline first example for option-chain-analytics: a synthetic Black-Scholes-
      Merton option panel with two observation times and three expiries, its ATM strike and
      volatility, and a weekly roll expiry.
---

# First success

*Author: [Artur Sepp](https://github.com/ArturSepp) / First recorded: [2026-08-16](https://github.com/ArturSepp/OptionChainAnalytics/commit/312512765e5dcdd44fdd90103a26eac6837640ff)*

Source: [OptionChainAnalytics](https://github.com/ArturSepp/OptionChainAnalytics).
Software citation: [CITATION.cff](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/CITATION.cff).

This example is the release-gating public workflow. It creates two observation times, three
expiries, five strikes, calls and puts, and an aligned spot series. Prices and Greeks are generated
deterministically with Black-Scholes-Merton; there is no random state, network access, credential,
or local-data dependency.

## Reproducible released workflow

The tested support floor for this first-use workflow is **option-chain-analytics 5.3.0** on
Python 3.12. This is a verified floor, not the historical introduction version. Install core
without extras; save and run the existing package-owned script in a working directory outside
synchronized folders:

```powershell
python -m pip install "option-chain-analytics==5.3.0"
python -c "from importlib.metadata import version; import option_chain_analytics as p; print(version('option-chain-analytics')); print(p.__file__)"
Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/ArturSepp/OptionChainAnalytics/1443fe313336967b6aac78bf0bc9771aae3fd565/examples/first_success.py' -OutFile first_success.py
python first_success.py
```

Installation and saving the script need internet access; the calculation below runs offline.
Measure installation separately from execution, and allow any first Numba compilation to finish.
No universal time-to-first-result is promised.

This deterministic CPU workflow uses two synthetic observation times, three expiries, five strikes, calls and puts, and aligned spot values. It prints 30 contracts at the first observation, front-expiry ATM strike/volatility and the weekly roll expiry. Observation selection is exact by default; a previous-observation request must never select a future row. This is a synthetic Black-Scholes-Merton fixture, not empirical data or a calibrated market surface. No quotes, credentials, provider SDK, Arrow cache, files or network are required. Bloomberg/Tardis/CBOE access and provider-specific licensing belong to their documented optional routes.

[Stable documentation](https://optionchainanalytics.readthedocs.io/en/stable/) is the release channel;
[latest](https://optionchainanalytics.readthedocs.io/en/latest/) follows main and may include unreleased changes. Check the build's
source version; a stable alias is not proof of the latest PyPI upload. Existing figures,
results and conventions below remain the canonical example's contract.

From the repository root, run:

```bash
python examples/first_success.py
```

The executable source is included directly below.

```{literalinclude} ../examples/first_success.py
:language: python
:linenos:
```

The output must end with a finite ATM strike/volatility and
`weekly_roll_expiries=['12Jan2024']`. Tests also verify deterministic equality, declining time to
maturity for the same contracts, quote ordering, and put-call parity.

The synthetic surface is a fixture, not calibrated market data. It is intended for tutorials,
visualisations, and integration tests; empirical conclusions require a documented empirical feed.
