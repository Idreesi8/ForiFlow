# ForiFlow improvements — 22 October 2026

The subsequent [follow-up report](continuation-2026-10-22.md) records the latest
reminder and recovery changes, bundle size and complete regression counts.

The application now loads its trained ensemble on native Windows, stores a
transparent statement cash-flow sensitivity check, reports model readiness
honestly, and loads dashboard pages on demand. These are unreleased local
changes to the current application. The archived v2.3.2 packages were reviewed
but were not merged wholesale.

## Trained model on Windows

The original Linux-created XGBoost pickle included a training RNG snapshot that
the installed Windows wheel could not restore. XGBoost distinguishes portable
model files from training snapshots; the upstream Windows RNG issue is
documented in [issue 12459](https://github.com/dmlc/xgboost/issues/12459) and its
[model IO documentation](https://xgboost.readthedocs.io/en/stable/tutorials/saving_model.html).

`backend/ml/artifact_loader.py` locates the original `Model` object within the
snapshot and passes those unchanged XGBoost-generated UBJSON bytes to supported
model IO. It does not rebuild model JSON, rewrite artifacts, restore training
RNG state, or patch global unpickling hooks. Its instance-local loader handles
the project's trusted, uncompressed joblib artifacts only. It does not make
pickle safe for uploads and must not be used as a training-resumption loader.

Parity tests compare predictions, feature contributions, feature names,
attributes and serialized model bytes exactly for a freshly trained test
Booster. The shipped ensemble also passes its real-model and approval-path
regressions on Windows. All 31 pre-existing files under `backend/ml` retain
their earlier recorded hashes. The model fingerprint remains:

```
15a24f14f148b513bddf75c5eafb55f873af8d57f42988970fc51247686ff43d
```

Production now refuses an unintended `artifacts_missing` or `load_failed`
fallback. Development can retain the demonstration fallback, but health is
degraded and the result explicitly labels formula scoring. An intentionally
pinned demonstration engine remains supported.

## Statement cash-flow resilience

New assessments with a statement store `principal-stress-v1` in existing
turnover-evidence JSON. No schema migration is needed. For each observed full
calendar month, each scenario calculates:

```
remainder = recorded inflow × (1 − decline / 100)
            − recorded outflow − requested principal / tenure in months
```

Declines are 0%, 10%, 20% and 30%. Results include months whose remainder is at
least zero, months observed, median remainder and lowest remainder. Counts use
unrounded values; displayed money rounds half up to paisa. Interior quiet
months stay in the denominator. Incomplete boundary months remain excluded by
the existing statement rules.

For six months each receiving PKR 100,000 and paying PKR 60,000, a PKR 900,000
request over 36 months has PKR 25,000 of new monthly principal:

| Inflow scenario | Months covering principal | Median left after payment |
| --- | --- | --- |
| Recorded | 6 of 6 | PKR 15,000.00 |
| 10% lower | 6 of 6 | PKR 5,000.00 |
| 20% lower | 0 of 6 | −PKR 5,000.00 |
| 30% lower | 0 of 6 | −PKR 15,000.00 |

This is a historical replay and sensitivity calculation, not a default
prediction, DSCR, actual installment schedule, affordability verdict or
approval. Interest and fees are excluded. Receipts may include owner transfers
and recorded outflows may include existing debt payments. An officer must
verify completeness, classification and actual repayment terms. Missing
months cannot be distinguished from omitted export data automatically.

The frontend displays stored server calculations in the intake result and
officer review. The printable memo includes recorded and 20%-lower scenarios.
The memo carries the complete statement fingerprint and labels its monthly
request amount as principal only, excluding costs.
Existing applications without this evidence do not acquire invented results.
The model score and policy recommendation remain unchanged by these scenarios.

Each new statement assessment records parser version `statement-v2`, unreadable
row count, quiet months, and SHA-256 of the exact CSV text accepted by the API,
encoded as UTF-8. This identifies that submitted text; it does not authenticate
a bank source or guarantee identity with an original file's byte encoding.
Parser version and fingerprint also accompany the application-created audit
entry. New assessments only claim statement agreement when both submitted
turnover inputs equal the parser's suggested whole-rupee amounts exactly.
Old stored evidence is not rewritten.

## Dashboard loading

React pages load on demand with a loading state inside the persistent officer
workspace. The production main JavaScript entry decreased from 860.39 kB
(244.62 kB gzip) to 252.35 kB (85.12 kB gzip), approximately 71% smaller before
compression. Route and chart chunks download when required; this is a bundle
measurement, not a measured network or scoring latency improvement.

## Verification

The full native Windows backend run completed with **568 passed, 51 skipped,
zero failures and zero errors** in 386.77 seconds. One installed
Starlette/httpx TestClient deprecation warning remains; it is not a test
failure. PostgreSQL-specific skips are not evidence that those checks passed.

| Check | Result |
| --- | --- |
| Complete backend suite | 568 passed, 51 skipped; 619 collected |
| Frontend unit tests | 27 passed |
| Frontend production build | Passed; no chunk above 500 kB |
| Browser | CSV upload, scoring result, lazy route navigation, detailed statement replay, 390-pixel mobile overflow, saved memo and print rendering passed; zero page runtime errors |
| Model byte preservation | 31 pre-existing model-directory files unchanged |
| Diff whitespace/error check | Passed |

The Chrome browser run uses synthetic statement/application fixtures generated
through the actual native ML scorer and an isolated SQLite test API. Browser
API responses are intercepted with those fixtures; this is not a live
PostgreSQL end-to-end or production load test. Its synthetic application score
was 24.41 with `scoring_engine=ml`. Backend tests separately exercise the real
API/model path. Screenshots were visually inspected at desktop and mobile
sizes. Temporary verification records are retained in the private archive.
The evidence is under `archive/improvements-2026-10-22/`; the memo fixture is
synthetic and its PDF spans two A4 pages.

The complete test suite previously stopped with 42 model setup errors on
Windows. After the loader fix, a first full run exposed an older fingerprint
test that did not apply the application's existing JSON newline
normalization. The test now independently applies that established rule;
production fingerprint behavior did not change.

## Practical limits

- The shipped model remains a public consumer-credit demonstration model.
  Its published final-test AUROC remains 0.7748. No new predictive-accuracy
  claim, Pakistani SME validation, bank certification or live bank integration
  is implied by these improvements.
- Docker was unavailable on this laptop. PostgreSQL-specific integration
  tests require a configured PostgreSQL instance and were not verified here.
- No deployment, production migration, account changes, model retraining or
  real customer-data edits were performed for these improvements.
