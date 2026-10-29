# Cash-flow Intelligence — 28 October 2026

ForiFlow now includes a separate **Cash-flow Intelligence** workspace at
`/cashflow`, available through Monitoring and the workspace finder. It turns a
statement into local time-series analysis without creating a borrower,
assessment, recommendation or officer decision. It makes no external AI call
and requires no new service subscription, API credential or model download.

## What the user can do

Choose a CSV, paste its contents, or load the clearly labelled synthetic
36-month example. The workspace shows the latest receipts on a chart, a robust
trend, the median change between two recent three-month blocks, negative-net
month counts and retained monthly figures. Displayed amounts retain paisa
precision. No foreign currency is automatically converted or relabelled as PKR.
ISO `YYYY-MM-DD` source dates avoid ambiguous day/month ordering.
The [source-quality update](cashflow-source-quality-2026-10-28.md) adds explicit
numeric date conventions, repeated-row inspection and two source fingerprints
in `cashflow-local-v2`. The forecasting protocol below remains unchanged.

Historical analysis needs 3–120 parser-retained calendar months. A forecasting
comparison needs at least **30 months**, with no unreadable source rows, no
retained months without readable transactions and no future-dated transaction.
Short or problematic sources still get descriptive history; their forecast is
withheld with an explanation. An old source produces a source-anchored estimate,
not necessarily a forecast for the current calendar month.

## Technology and protocol

The robust trend uses the Theil–Sen median of pairwise slopes over at most the
latest 12 months, with a joint median-residual intercept. This resists individual
large observations better than a least-squares fit, but does not establish a
statistically significant change or verify revenue. The implementation uses
bounded, deterministic local arithmetic; it does not train a credit model.
The [SciPy method reference](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.theilslopes.html)
describes the slope estimator and supported intercept definitions.

Four one-step receipt methods are fixed since `cashflow-local-v1` and retained
in `cashflow-local-v2`:

| Method | What it reads before a forecast origin |
| --- | --- |
| Last-month baseline | Previous observed month |
| Six-month median | Six previous months |
| Robust trend | Theil–Sen line over twelve previous months |
| Same month last year | Observation twelve months earlier |

The latest 30 retained observations are used in chronological order:

1. First 12 initialise history.
2. Next 6 are development origins. Lowest mean absolute error, rounded to paisa,
   selects the method. Ties follow the table order, favouring the baseline.
3. Next 6 calibrate a radius equal to the largest absolute error of that already
   selected method. They do not select or tune the method.
4. Final 6 evaluate the frozen method choice and radius against later outcomes.
   Each origin reads only preceding observations. Earlier evaluation outcomes
   become part of the history available to subsequent origins, as in a monthly
   one-step forecasting workflow.

The next source month uses the selected method and latest available history.
All receipt estimates are constrained to be nonnegative. The chart/history
table show at most 36 months. Sources over 120 retained months and monthly totals
above PKR 1 trillion are refused rather than clipped.

This follows the principle of [rolling forecasting origins](https://otexts.com/fpp3/toolbox.html#time-series-cross-validation):
forecasts must be evaluated using earlier observations to predict later ones.
The particular 12/6/6/6 protocol is ForiFlow's fixed design, not a claimed
industry standard or an externally validated SME method.

## The range is deliberately empirical

The displayed range is point estimate ± the largest error in the six calibration
months, with its lower end bounded at zero. It has **no nominal probability or
future-coverage guarantee**. It is not sold as a conformal guarantee or confidence
interval. A zero-width range only means zero errors in that short past window.
The page shows how many of the six later observations actually fell within it,
and compares mean absolute error with the simple last-month baseline, including
when the selected method underperforms. Six evaluation months are a small sample.

Receipts are account inflows, not verified sales, profit, free cash flow or
repayment capacity. Transfers and borrowing may be included; cash sales and other
accounts may be absent. Structural changes can invalidate the estimate. No
interest, fees, debt schedule or credit-default outcome is inferred.

## Actual synthetic-example result

The checked-in example is generated deterministically in
`frontend/src/lib/cashflowIntelligence.js` and also provided as
`docs/samples/cashflow-intelligence-synthetic-36-months.csv`. It contains 36
populated months, October 2023–September 2026, with seasonal receipts, drift and
a recent slowdown. It is not real borrower data or a training dataset.

Computed results, not invented demonstration numbers:

- Method selected: same month last year.
- Development: April–September 2025; calibration: October 2025–March 2026;
  evaluation: April–September 2026.
- Later six-month MAE: **PKR 31,500**; last-month baseline: **PKR 64,000**.
- Empirical radius: **PKR 24,000**; only **3 of 6** later observations were inside
  the range. This illustrates why it must not be called a guaranteed interval.
- Next source month: October 2026. Point estimate: **PKR 398,000**; empirical
  range **PKR 374,000–422,000**.

These are results for a single synthetic example, not evidence of accuracy on
real SMEs, a trained model improvement, or an independently validated benchmark.

## Source and interaction integrity

`POST /model/cashflow-intelligence` requires an officer session. Its strict body
accepts only CSV text, reparsed on the server using the existing canonical
statement parser. Finite typed responses have `Cache-Control: no-store`.
No inference, model registration, case save, decision or database mutation occurs.
The browser independently hashes the exact decoded UTF-8 text and withholds a
result if its source fingerprint, method, chronology, observations or derived
error/band summaries are inconsistent.

Editing, clearing, replacing a file, cancellation and component unmount invalidate
earlier requests using abort and sequence guards. Failures retain the current
draft and allow another attempt. The example cannot replace a nonempty draft.
Navigation/sign-out use the existing unsaved-work protection. Drafts are not
persisted and cannot be recovered after a tab/browser crash.

The canonical parser's first/last transaction dates and day-5/day-25 boundary
heuristic cannot verify a complete reporting period. Quiet months remain zeros
in historical figures. Unreadable rows and quiet months therefore withhold the
new forecasting comparison. No existing scoring or historical evidence schema
was changed by this feature.

## Verification and live deployment

- 65 focused backend checks passed on Windows and in the final Linux image.
  The Linux run had no network, a read-only root filesystem, a temporary `/tmp`
  and no pilot database or secrets mounted. The two runs repeat the same 65
  checks; they are not 130 distinct tests.
- 92 frontend unit checks passed, including real UTF-8 fingerprinting,
  chronological/metric/range validation and the exact two-decimal synthetic CSV.
- Final native and Docker production builds passed. Deployed schema, service and
  endpoint source hashes match local files. The live service reports ready with
  its existing ML credit engine.
- 16 browser checks passed, covering actual forecasts, keyboard disclosure,
  empty/short/gap sources, failed-request retry, wrong-source withholding,
  cancellation, draft retention, unsaved navigation, explicit clear, live search,
  paisa precision and desktop/mobile layout. The synthetic example was also
  analysed through the actual live backend; no real borrower statement was used.
- All 10 full-table database fingerprints, the database image and all six
  serving-model artefacts match the pre-deployment snapshot. No live assessment,
  officer decision or policy was created or changed.
- Existing frontend/backend images were tagged for rollback. A new database
  dump was created and its archive contents validated with `pg_restore --list`;
  this was not a new full restore exercise.
- Temporary QA helpers were stopped after checking their process identities.
  Browser sizing was restored and the live synthetic example remains open.

Local evidence is retained under `archive/cashflow-intelligence-2026-10-28/`.
The accepted readable result screenshot is `live-synthetic-forecast-proof.jpg`.
It displays synthetic example estimates, not actual borrower finances.
