---
myst:
  html_meta:
    description: >-
      Diagnose observed option quote quality, synchronized put-call parity and
      point-in-time source-row provenance with immutable OCA reports.
---

# Quote quality, parity and provenance

*Author: [Artur Sepp](https://github.com/ArturSepp)*

Implemented in [option-chain-analytics](https://github.com/ArturSepp/OptionChainAnalytics).
Software citation: [CITATION.cff](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/CITATION.cff).

Quote diagnostics record whether observations are usable under declared conventions and show
which reconstruction or selection rule retained each source row. They leave observations and
existing cleaning policies unchanged. OCA owns observed-data evidence; fitted-surface checks
belong to [StochVolModels](https://github.com/ArturSepp/StochVolModels).

## Inputs and conventions

`QuoteDiagnosticConfig` requires explicit price units. `price_conversion="quoted"` retains the
source units; `"usd_per_unit"` multiplies bid/ask prices by `usd_multiplier` once. Contract size
is recorded separately and never multiplied into a per-unit residual. Bounds and parity require
`price_unit="USD per unit"`, `payoff="standard_european"` and `settlement="cash"` or `"physical"`.
These declarations assert a verified normalization contract. Currency conversion alone does
not establish that inverse-option payoffs satisfy standard European parity.

Volatility is decimal, maturity is in years, and ages are in seconds. Requested and actual
source times are distinct, timezone-aware instants. Missing exchange times remain unchecked;
naive row timestamps are not silently assigned a timezone. A snapshot later than its request
is rejected. Discounts greater than one are valid, including under negative rates.

An exchange/provider timestamp identifies the clock supplied by that feed. It does not
establish when a historical record became available to a collector. Keep receive times
unknown when the archive does not contain them, and state which clock underlies a study's
point-in-time claim. A common forward/discount policy must be validated for the declared
payoff and frozen before downstream fitting; relabelling units does not validate that policy.

Optional age and relative-spread thresholds are fixed caller inputs. No threshold is estimated
from future observations. `year_basis` and `delta_convention` remain unknown unless supplied.
Delta ranges describe the observed column under that recorded convention.

## Diagnose observations

`diagnose_quotes` accepts a raw normalized snapshot before deduplication or an existing
`SlicesChain`. A chain cannot recover source rows already removed, so its report marks
pre-reconstruction counts unavailable. The report includes:

- `quotes`: stable source-row IDs, normalized prices, timing, validity and reason codes;
- `checks`: separate status, severity, reason and value for each row/check;
- `expiries` and `summary`: counts, unique strikes/contracts, synchronized call/put coverage,
  IV availability, spread/age distributions and strike/log-moneyness/delta ranges;
- `targets`: explicitly missing requested maturity IDs.

Statuses are `pass`, `fail`, `not_checked` and `not_applicable`. Missing IV does not erase valid
price evidence. Zero bids and locked markets have their own counts. Bounds test whether the
quote interval overlaps the admissible standard-payoff range; they are not a demand that every
bid equal an attainable model value. For forward $F$, strike $K$ and positive discount $D$,
the admissible call and put ranges are

$$
[D\max(F-K,0),\;DF],\qquad [D\max(K-F,0),\;DK].
$$

For lower and upper bounds $L,U$, the reported margin is
$\min(\mathrm{ask}-L,\;U-\mathrm{bid})$; it passes when at least
`-config.price_tolerance`, in the declared price units.
Numerical lower bounds use the zero-volatility intrinsic payoff from
[VanillaOptionPricers](https://github.com/ArturSepp/VanillaOptionPricers) at unit discount,
then multiply by $D$ exactly once. This also applies when $D>1$. A locked quote at the
discounted intrinsic bound passes; a locked quote below it by more than the tolerance fails.
The spread floor used
for residual scaling does not relax these bounds or make an inadmissible price valid.

## Parity and optional inference

`diagnose_parity` consumes a quote report. Each pair must have the same underlying, maturity,
expiry, strike and exchange time, with exactly one call and put. Missing, asynchronous,
crossed or ambiguous duplicate legs remain unchecked. Declared forwards and discounts must
agree between legs.

The observed parity interval is call bid minus put ask through call ask minus put bid.
The declared model value is discount multiplied by the difference between forward and strike. Reports include the signed
midpoint residual, distance outside the interval, and residual divided by the larger of the
combined half-spread and an explicit positive `spread_floor`.

`refit=True` calls the existing
[`imply_forward_discount_from_bid_ask_prices`](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/src/option_chain_analytics/utils/forward_discount.py)
without changing it. Its inverse-spread weighting and Huber reweighting remain intact.
Supplied `discount_anchor` stays fixed; optional bounds are explicit and do not assume positive
rates. A dimensionless strike-design condition number flags nearly coincident strikes; one
pair cannot identify a free discount. An explicit rate anchor can permit an otherwise sparse fit.

The report distinguishes eligible, used and rejected strikes. Internal robust weights are not
reported as hard exclusions. Refitting the same quotes measures internal consistency, and a
successful fit does not clear failures against the originally supplied forward/discount.
Neither result establishes executable arbitrage after financing, costs and synchronization.

## Preserve reconstruction evidence

`reconstruct_with_diagnostics` calls the existing `create_chain_at_time` API and returns the
same chain plus a sidecar. `previous` selects one whole earlier snapshot; it does not fill
individual contracts from other timestamps. Before the first observation it returns no chain
and an empty report with an explicit unavailable-selection status.

The `provenance` table identifies original history row positions and explains contract
deduplication (keep first), expiry reconstruction exclusions and per-side strike deduplication
(keep last). The `counts` table reconciles input, unique-contract, retained-slice and excluded
rows. IDs are stable for repeated requests against the same history, not across reordered or
revised datasets. Canonical frames and caches acquire no diagnostic columns.

`QuoteDiagnosticReport.to_dict()` produces strict JSON; `from_dict()` restores it. Non-finite
metrics become null alongside status/reason. Tables and metadata access return independent copies.

## Handoff to SVM research diagnostics

Preserve the complete quote-quality report, its parity report, configuration, source and
requested times, and the source-row IDs of the selected calibration quotes. The optional
SVM adapter's selection map connects those IDs to the new `OptionChain`; default row
ordinals after filtering are not substitutes for source identities.

SVM's repository-only
[combined research report](https://github.com/ArturSepp/StochVolModels/blob/main/examples/calibration/combined_research_diagnostics.py)
accepts serialized OCA reports without importing OCA. It checks selected prices, IVs,
strikes, option types, maturities, forwards, discounts, units and timestamps before joining.
It reports quote quality, parity, observed fit, strike support and wing sensitivity as
separate facets. OCA remains the owner of observation diagnostics and never imports SVM.

In that consumer, unchecked age or missing source time makes quote quality unavailable;
an observed quality failure remains a failure. Missing or unchecked selected parity pairs
stay unavailable. Such upstream evidence blocks a research sensitivity classification,
while observed-fit residuals and their exclusions remain visible. Neither passing parity
nor a low fitting error validates extrapolated wings.

The public diagnostics do not estimate an empirical quote-error distribution. For a study
using temporal residuals, retain the calibration/validation split, the market adjustment,
the forward/discount policy and the price/payoff mapping as separate frozen evidence.
A temporal change is not automatically an independent quote-level error. Tail dependence,
spread floors and price-bound admissibility need their own evaluation before a noise law
can drive SVM refits. The synthetic Gaussian-IV cutoff contract in SVM does not establish
eligibility for an empirical OCA surface.

## Retrospective event freshness and asynchrony

The repository-only `examples/retrospective_freshness.py` assesses provider-event
cadence using an explicitly frozen research policy. It does not change
`QuoteDiagnosticConfig`, reconstruction, caches or the exact-time parity rule.
Provider event age is the elapsed time from the event timestamp to the requested
analysis time. It is distinct from last quote-update age and collector receipt latency.

`fit_event_policy` accepts calibration inventory only and rejects observations at
or after the declared split. Inventory identifies each source row, contract, actual
expiry, requested time and provider event time. Prices, fitted results and model
selection flags do not determine its timing budgets. The reference policy uses the
nearest-rank 95th percentile, capped at an explicit 3,600-second research ceiling:

- Quote-event age uses all nonfuture, unexpired calibration inventory rows.
- Anchor age uses the youngest event in each complete calibration expiry/snapshot group.
- Cross-quote asynchrony uses each complete group's oldest-to-youngest event-time range.

The quantile and cap are research choices. Their budgets describe the observed
calibration cadence; held-out coverage does not establish an economically acceptable
freshness limit. A missing calibration population produces an unavailable budget.
The policy records its calibration denominators, input fingerprint, split and digest.
`apply_event_policy` applies the frozen artifact without fitting on validation.

For example, event ages of 10, 10, 30 and 30 seconds have a nearest-rank median of
10 seconds, a youngest-event age of 10 seconds and a time range of 20 seconds.
An age exactly equal to its budget passes. Missing or naive event clocks remain
unavailable, future events fail and expired observations are inapplicable. Known
timing failures stay visible when other clocks are missing. Every input row remains
in the immutable row/group report.
With incomplete clocks, the youngest-event age remains unavailable: an unknown event
could be newer. A known excessive time range can still fail despite missing clocks.

`selected_qualification` assesses the original selected source IDs without changing
the selection. It reports original quote quality, retrospective event quality,
timing and exact-source parity separately. Retrospective event quality combines the
selected non-age quote checks with the frozen age, anchor and asynchrony checks.
The latest observed event is labelled an event anchor; it never substitutes for a
snapshot receipt timestamp. Original snapshot-age evidence remains unchanged.

A separately declared SVM research gate can combine this conditional event evidence
with saved-fit success, the original native input guard and complete passing original
parity. This is separate from SVM's existing strict gate. A bounded cross-strike time
range never synchronizes a call and put with different event times. Missing or failed
parity continues to block qualification, and zero qualified groups is a valid result.
Neither gate establishes hidden wing accuracy or verified historical receipt availability.

Run the deterministic, credential-free example from a source checkout:

```console
python examples/retrospective_freshness.py
```

For an empirical before/after study, preserve the source panel, original selections,
saved fits, common-forward policy and calibration/validation split. Freeze the timing
policy before evaluating validation, retain separate cohort counts and blocking reasons,
and verify parent hashes before and after execution. Research inputs and generated reports
remain private local artifacts. No default age policy or automatic warning is installed.

## Offline example and public entry points

```python
import pandas as pd
from option_chain_analytics import (
    QuoteDiagnosticConfig, generate_simulated_options_data, reconstruct_with_diagnostics,
)

data = generate_simulated_options_data()
requested = data.get_timeindex()[0] + pd.Timedelta(seconds=60)
config = QuoteDiagnosticConfig(
    "USD per unit", payoff="standard_european", settlement="cash",
    max_quote_age_seconds=30, max_snapshot_age_seconds=30,
)
chain, report = reconstruct_with_diagnostics(
    data, requested, config=config, spread_floor=0.01, time_selection="previous",
    refit_parity=True,
)
assert report.table("counts").reconciled.all()
assert report.table("summary").snapshot_age_status.iloc[0] == "fail"
```

The canonical [example](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/examples/quote_diagnostics.py)
injects one crossed quote and one duplicate into the existing deterministic generator. It
asserts 31 source rows, 30 retained slice rows and a stale 60-second snapshot. Its 100×
quotation variant preserves the same normalized prices with an independent contract size of 0.1.

```console
python examples/quote_diagnostics.py
```

`plot_quote_diagnostics(report)` returns an optional figure with quote-quality annotations
and parity residuals. Numerical reporting does not require figure generation. Existing
`run_chain_report` defaults are unchanged. All six diagnostic symbols are available from the
package root; numerical symbols also live in `option_chain_analytics.diagnostics`.

The implementation requires OCA 5.3 or later. It adds no provider requirement. Maintainer
Windows checkouts use the external environment and runtime setup specified in AGENTS.md.
The SVM 2.5 optional adapter accepts this sidecar as `quality_report`, validates units/times
and selected prices, and adds a complete source-to-calibration selection map.

## See also

- [Schema contract](schema.md) and [point-in-time reconstruction](point_in_time.md).
- [First success](first_success.md) and [chain queries](queries.md).
- [SVM surface diagnostics](https://github.com/ArturSepp/StochVolModels/blob/main/docs/surface_diagnostics.md).

## References

- [OCA parity inference source](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/src/option_chain_analytics/utils/forward_discount.py).
- [VanillaOptionPricers software citation](https://github.com/ArturSepp/VanillaOptionPricers/blob/main/CITATION.cff).
- [option-chain-analytics software citation](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/CITATION.cff).
