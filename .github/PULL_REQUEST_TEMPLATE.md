## What changed

Describe the problem and the smallest coherent change that solves it.

## Verification

List the exact commands run and their results.

## Checklist

- [ ] Tests cover the changed public behavior or defect.
- [ ] Point-in-time code uses no observations later than the requested observation time.
- [ ] Timezone, volatility, rate, dividend, spot/forward, multiplier, and price conventions remain explicit.
- [ ] No credentials, private/licensed data, local paths, generated outputs, or agent reports are included.
- [ ] `ruff check src tests examples tools docs/conf.py` passes.
- [ ] User-visible changes are documented in `CHANGELOG.md` and relevant docs.
- [ ] New runtime dependencies or public-signature changes are called out explicitly.
