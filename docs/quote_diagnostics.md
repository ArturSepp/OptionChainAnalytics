---
myst:
  html_meta:
    description: >-
      Diagnose option quote quality and exact-time parity, freeze retrospective event
      freshness policies, and attribute missing or recoverable parity evidence for SVM research.
---

# Quote quality, parity and provenance

*Author: [Artur Sepp](https://github.com/ArturSepp) / First recorded: [2026-10-12](https://github.com/ArturSepp/OptionChainAnalytics/commit/e366e90f91ecd03f77d518786f3d089b8a5ddff4)*

Implemented in [option-chain-analytics](https://github.com/ArturSepp/OptionChainAnalytics).
Software citation: [CITATION.cff](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/CITATION.cff).

Quote diagnostics record whether observations are usable under declared conventions and show
which reconstruction or selection rule retained each source row. They leave observations and
existing cleaning policies unchanged. OCA owns observed-data evidence; fitted-surface checks
belong to [StochVolModels](https://github.com/ArturSepp/StochVolModels).

## Choose a diagnostic workflow

| Question | Entry point | Availability and result |
|---|---|---|
| Are the observed quotes valid under stated units and clocks? | `diagnose_quotes` | Packaged API; immutable quote/check tables and coverage counts |
| Do synchronized call/put intervals contain declared parity? | `diagnose_parity` | Packaged API; exact source pairs, residuals and optional inference |
| Which original rows survived reconstruction? | `reconstruct_with_diagnostics` | Packaged API; chain plus source-selection sidecar |
| Does selected event timing meet a calibration-frozen research policy? | `fit_event_policy`, `apply_event_policy`, `selected_qualification` | Repository-only [freshness example](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/examples/retrospective_freshness.py); original quality and conditional event quality remain separate |
| Why is selected parity missing or failing, and can original records resolve it? | `attribute_parity` | Repository-only [attribution example](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/examples/parity_attribution.py); quote, inventory-pair and group evidence |

The packaged diagnostics require OCA 5.3 or later. The research helpers require a
source checkout containing the linked files; they are not package-root exports or
installed command-line tools. A private panel's forward policy, noise profiles and
qualification decisions are study artifacts, not additional normalization defaults.
For fitted-price, surface and longitudinal interpretation, continue with the
[SVM workflow](https://github.com/ArturSepp/StochVolModels/blob/main/docs/surface_diagnostics.md#user-content-select-a-diagnostic-workflow).

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
[D\max(F-K,0),\quad DF],\qquad [D\max(K-F,0),\quad DK].
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

The repository-only [freshness example](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/examples/retrospective_freshness.py) assesses provider-event
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

The input inventory contains `group_id`, `source_row_id`, `contract`, `requested_time`,
`expiry`, `event_time`, `strike` and `optiontype`. A group identifies one actual
expiry at one requested time. Source-row and contract identities must be unique within
each group, and times must be aware;
missing event clocks remain unavailable. Supply all original inventory rows when
estimating the policy, then use the unchanged selected IDs for qualification.

For requested time $t_g$ and provider-event time $t_i$, define event age
$a_i=t_g-t_i$ in seconds. On a complete group of nonfuture events, youngest-event age
and cross-quote time range are

$$
a_{\mathrm{anchor}}=\min_i a_i,
\qquad r_{\mathrm{events}}=\max_i a_i-\min_i a_i.
$$

These are event-cadence statistics. Neither is a receipt timestamp or an estimate
of the time since a bid or ask last changed.

| Output | Evidence retained |
|---|---|
| Frozen policy dictionary | Split, calibration denominators, input fingerprint, budget values and policy digest |
| `apply_event_policy(...).table("rows")` | Every original source row, event age, status and reason |
| `apply_event_policy(...).table("groups")` | Group anchor age, asynchrony, completeness and status |
| `selected_qualification(...)` dictionary | `original_quality`, `event_quality`, `exact_parity`, `timing`, reasons and available timing details |

An empty selection returns unavailable qualification. A known failure dominates
missing evidence; otherwise every required selected check must be supported before
the corresponding group can pass. These helpers do not modify the original quality
report, select a different contract or change a downstream gate.

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

## Parity attribution and recovery from original evidence

The repository-only [attribution example](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/examples/parity_attribution.py) traces each selected source ID
to its original exact-time call/put evidence and repeats `diagnose_parity` on the
unchanged complete quality sidecar with `refit=False`. `attribute_parity` returns an
immutable report with selected-quote, inventory-pair and group-summary tables. It
requires the original selected IDs, group identity and explicit calibration/validation
split. Missing selections or contradictory quote/parity identities and clocks are errors.

| Input | Contract |
|---|---|
| `quality`, `parity` | Original `QuoteDiagnosticReport` objects or their serialized dictionaries; matching configuration and source/request clocks |
| `selected_ids` | Original selected source IDs in their retained order, without duplicates |
| `group_id`, `split_utc` | Explicit group identity and aware cohort boundary; no threshold fitting uses validation |
| `priority` | Reporting label only; it does not remove other observations or change a decision rule |
| Optional `context` | Explicit `mapping="inverse_forward_value_D1"` and original source records for the separate forward comparison |

Attribution distinguishes missing identity or clocks, future or expired observations,
absent opposite legs, opposite legs observed only at different times, ambiguous exact
legs, invalid inputs, passing intervals and common-forward interval failures. The
counterpart IDs, event clocks and minimum observed nonfuture time gap are retained.
The gap is descriptive: it never permits nearest-time pairing. Several causes may
coexist in a group; an empty selection remains unavailable.

A quote is recoverable only when an omitted or incorrectly reported pair passes after
recomputation from the original exact observations in the original common coordinates.
Already supported pairs, retained failures and original checked results that cannot be
reproduced have separate labels. New reports never overwrite the original sidecars.

An optional, explicitly declared inverse forward-value/D=1 context can compare a
checked exact pair with its coherent original provider forward and original coin
premiums. Source IDs, contract/expiry/strike identities, event clocks, common forward
and original premium scaling must reproduce the frozen observations. Let $q_t$ be an
original coin premium, $F_t$ the pair-event provider forward and $F_\star$ the frozen
common expiry forward. The local comparison uses $F_tq_t$ and $D=1$, with actual-event
ACT/365 maturity and the original price tolerance. The saved common-coordinate
premiums $F_\star q_t$ and their original maturity remain unchanged. It calls OCA diagnostics without
fitting forwards or discounts. Missing or inconsistent original forwards remain
unavailable. Common-coordinate implied volatilities are not reused at the local forward.

For example, common forward $F_\star=100$ and strike $K=100$ with call 20–22 and put 3–5
give a parity interval 15–19, which excludes $F_\star-K=0$. If the original coin premiums
are 0.20–0.22 and 0.03–0.05 at a coherent original forward $F_t=120$, the separate
local interval is 18–22.8 and contains $F_t-K=20$. The common-forward pair still
fails. This comparison shows dependence on representation; it does not establish
market movement, repair the common surface or demonstrate executable arbitrage.

The optional context's `rows` identify `source_row_id`, `contract`, `underlying_index`,
`mat_id`, `expiry`, `strike`, `optiontype`, `requested_time` and `event_time`. They
also supply `native_bid`, `native_ask`, `source_forward`, `common_forward` and, when
known, `common_anchor_time`. Original coin prices multiplied by the common forward
must reproduce the saved normalized quotes. A missing context row leaves its local
comparison unavailable; conflicting identities, clocks or premium scaling are errors.

| Report table | Unit of observation and use |
|---|---|
| `quotes` | One original selected quote; old/new parity state, counterpart IDs/clocks, attribution, observed gap and recoverability |
| `pairs` | One exact inventory group, including unmatched single legs; selected-leg count and separate common/local interval results |
| `summary` | One expiry/snapshot group; original and recomputed selected-parity state, split, priority label, counts and multiple causes |

Inventory pair groups are not all checked call/put pairs. Keep their denominator
separate from selected quotes and from groups. Selected group status is `fail` if
any selected pair fails, `pass` only for a nonempty selection whose pairs all pass,
and `unavailable` otherwise. A failing group can also have missing pairs.

Attribution recovery means recovering previously omitted or incorrectly reported
evidence at the same frozen observation. SVM's longitudinal observed recovery means
new clear evidence at a later eligible observation; neither missing data nor elapsed
time supplies that evidence. The two meanings should not share an unqualified count.

Run the credential-free demonstration from a source checkout:

```console
python examples/parity_attribution.py
```

A frozen-panel study should prioritize a previously declared cohort without dropping
other groups, retain the original source and selected IDs, and report each split
separately. Replaying qualification may substitute only recomputed common-coordinate
parity evidence. Pair-local passes cannot transfer into that gate. Preserve parent
hashes, frozen event-quality policy, saved fits and native guards; receipt availability
and economically acceptable freshness remain unresolved by this attribution.

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
- [SVM longitudinal replay](https://github.com/ArturSepp/StochVolModels/blob/main/docs/surface_diagnostics.md#user-content-longitudinal-diagnostic-replay).

## References

- [OCA parity inference source](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/src/option_chain_analytics/utils/forward_discount.py).
- [Repository-only event policy source](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/examples/retrospective_freshness.py) and [parity attribution source](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/examples/parity_attribution.py).
- [VanillaOptionPricers software citation](https://github.com/ArturSepp/VanillaOptionPricers/blob/main/CITATION.cff).
- [option-chain-analytics software citation](https://github.com/ArturSepp/OptionChainAnalytics/blob/main/CITATION.cff).
