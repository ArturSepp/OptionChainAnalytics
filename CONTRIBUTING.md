# Contributing to OptionChainAnalytics

Thank you for considering a contribution. OCA is intentionally focused on point-in-time
option-chain containers, feed normalisation, reconstruction, and queries. Pricing belongs in
`vanilla-option-pricers`; generic analytics and plotting belong in `qis`; strategy backtests and
paper-specific portfolio logic belong in their research repositories.

## Before opening an issue

- Search existing issues and state the smallest reproducible task or defect.
- Do not attach proprietary, licensed, credentialed, or personally identifying data.
- For a data adapter, document the provider, access/licensing boundary, timezone, spot/forward
  convention, quote units, multiplier, and missing-data behavior.
- Report security concerns privately as described in [SECURITY.md](SECURITY.md).

## Development setup

OCA requires Python 3.14 or newer.

```bash
python -m venv .venv
python -m pip install -e ".[dev,docs]"
pytest -q
ruff check src tests examples tools docs/conf.py
sphinx-build -W -b html docs docs/_build/html
```

Run `python examples/first_success.py` to verify the credential-free public path. Before submitting
a packaging change, also run:

```bash
python -m build
python tools/verify_distribution.py dist
```

## Change requirements

- Preserve point-in-time behavior: code at observation time `t` must not use later observations.
- State volatility, rate, dividend, timezone, multiplier, and price conventions explicitly.
- Add focused tests for defects and public behavior. Numerical changes need an independent
  reference or invariant, not merely a snapshot update.
- Update `CHANGELOG.md` for user-visible behavior and documentation.
- Keep local datasets, generated outputs, credentials, and agent reports in the ignored `data/`,
  `outputs/`, and `agents/` directories.
- Keep pull requests focused; do not combine provider, schema, and strategy changes without a
  clear reason.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
