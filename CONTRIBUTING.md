# Contributing to OptionChainAnalytics

*Author: [Artur Sepp](https://github.com/ArturSepp) / First recorded: [2026-08-16](https://github.com/ArturSepp/OptionChainAnalytics/commit/312512765e5dcdd44fdd90103a26eac6837640ff)*

Implemented in [option-chain-analytics](https://github.com/ArturSepp/OptionChainAnalytics).
Software citation: [CITATION.cff](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/CITATION.cff).

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

## Starter tasks

These are bounded proposals, not assigned issues or confirmed defects. Recheck source and open
work before agreeing one task. Use the existing [feature form](https://github.com/ArturSepp/OptionChainAnalytics/issues/new?template=feature_request.yml),
Area **Documentation or example**. Include the task ID, owner, exact paths, reproduction, acceptance and focused
check under Proposed behavior; retain required boundary checkboxes. Use the bug form only for
observed incorrect behaviour. Keep numerical code, public signatures, dependencies, fixtures and
canonical examples unchanged for these documentation tasks.

### OCA-1: clarify synthetic first output

Owner: OptionChainAnalytics. Edit only `docs/first_success.md` to clarify one observed setup or output-reading ambiguity. Acceptance: identify the two observation times, 30 contracts and synthetic-data boundary without changing the example or expected values.

```console
python examples/first_success.py
python -m pytest tests/test_first_success.py -q
```

### OCA-2: clarify point-in-time selection

Owner: OptionChainAnalytics. Edit only `docs/queries.md` to clarify one exact/previous-observation selection example. Acceptance: no future observation, nearest lookup or backfill is implied; preserve timezone and missing-data conventions.

```console
python -m pytest tests/test_chain_loading.py -q
```

### OCA-3: check release and provider navigation

Owner: OptionChainAnalytics. Edit only `docs/first_success.md` to clarify stable/main or optional-provider navigation. Acceptance: retain the pinned canonical source and keep provider credentials, SDKs and licensed data outside the synthetic workflow.

```console
python -m pytest tests/test_project_metadata.py -q
```

Run the package's existing strict HTML command after a documentation edit and inspect the
changed passage. On the maintainer's OneDrive checkout, dot-source the shared
`Enter-AgentRepo.ps1` first and use `C:\Python\OptionChainAnalytics312\Scripts\python.exe`.
Keep exports, caches, builds and run output on C. The development setup below is for ordinary contributor
checkouts outside OneDrive; never create `.venv` in the synchronized checkout.

Follow the verification guidance in the [shared documentation standard](https://github.com/ArturSepp/ArturSepp/blob/main/docs/documentation_standard.md).
Record the revision, actual versions, exact checks and skips, rendered review and material
automation assistance. Preserve MIT licensing and attribution. Automated checks do not
establish independent reader success. Review time and acceptance are not promised.

## Development setup

OCA development requires Python 3.11 or newer. The full test matrix covers Python 3.11 through 3.14.

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

Keep automated checks in `tests/test_*.py`. Put a component development diagnostic beside its
implementation in the nearest `src/option_chain_analytics/**/run_local/<subject>_run.py`, using
`Locals` and `run_local(local=...)`. These implicit namespace folders intentionally omit
`__init__.py` and are excluded from built distributions. Broader public workflows stay in
`examples/`.

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
