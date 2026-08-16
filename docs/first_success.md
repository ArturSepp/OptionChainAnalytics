# First success

This example is the release-gating public workflow. It creates two observation times, three
expiries, five strikes, calls and puts, and an aligned spot series. Prices and Greeks are generated
deterministically with Black-Scholes-Merton; there is no random state, network access, credential,
or local-data dependency.

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
