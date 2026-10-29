# ForiFlow maintenance review — 22 October 2026

**Historical checkpoint:** the subsequent
[improvements report](improvements-2026-10-22.md) supersedes the Windows model
loading limitation below. This review preserves the original findings.

The statement calculation, validation and test-isolation fixes below are
verified. The complete application is **not yet verified**: native Windows
cannot load the committed XGBoost snapshot, and the local Docker engine was
unavailable for Linux/PostgreSQL verification.

## Changes delivered

- Include every calendar month between the statement's first and last readable,
  successful, non-zero transactions. Interior months with no transactions now
  contribute zero to turnover and consistency; partial boundary months remain
  excluded.
- Exclude non-finite amounts and report unreadable rows. Invalid debit/credit
  cells no longer silently become zero while the other cell is counted.
- Return statement validation errors for malformed CSV, oversized CSV fields,
  overflowing totals and non-finite ratios. Both statement preview and scoring
  refuse the invalid input; no application is saved.
- Isolate the test client's development/docs configuration from local `.env`
  settings. Test the environment-flag default with its input genuinely unset.
- Patch Vite from 6.4.3 to 6.4.5 and follow-redirects from 1.16.0 to 1.16.1.
  The manifest and lockfile include the Vite minimum-version update.
- Add 24 regression cases, including persisted evidence for quiet months.

For example, a January–June statement with PKR 100,000 received and PKR 60,000
paid in January, April and June previously reported three full months,
PKR 100,000 median inflow and 100 consistency. It now reports six months,
PKR 50,000 median inflow and zero consistency. This example assumes a complete
export: the parser cannot prove that an absent month represents no activity
rather than omitted source data. Officers must verify completeness.

## Verification

| Check | Result |
| --- | --- |
| Complete backend suite | **494 passed, 50 skipped, 42 setup errors** across 586 collected tests |
| Statement parser and related API/role/reminder tests | All 50 passed in the final suite |
| Configuration, docs, auth, audit, policy and security selection | 165 passed; four model-dependent cases deselected in this focused run |
| Frontend unit suite | 22 passed |
| Frontend production build | Passed using Vite 6.4.5 |
| Frontend dependency audit after patches | Zero reported vulnerabilities |
| Whitespace check | `git diff --check` passed |

Backend checks used Python 3.14.2 on Windows, XGBoost 3.4.0,
scikit-learn 1.8.0, SHAP 0.52.0 and NumPy 2.4.1. API tests required execution
outside the Windows sandbox because its local socket restriction prevented the
test client from creating its event loop. Test storage was in-memory SQLite.

## Remaining issues

1. **Native Windows model loading.** All 42 setup errors arise while loading
   the committed model: `XGBoostError: input stream corrupted` from
   `XGBoosterUnserializeFromBuffer`. The installed XGBoost and scikit-learn
   versions match the repository's serving pins. This resembles the upstream
   [Linux-to-Windows snapshot portability issue](https://github.com/dmlc/xgboost/issues/12459),
   where a maintainer identifies platform-dependent RNG state. That is a likely
   explanation, not a confirmed diagnosis of these specific artefacts.
   [XGBoost's model IO documentation](https://xgboost.readthedocs.io/en/stable/tutorials/saving_model.html)
   distinguishes stable `save_model` exports from non-portable pickle snapshots.
   Verify the existing artefacts in their Linux environment before attempting a
   portable export, then compare predictions and SHAP outputs across platforms.
   The trained artefacts and published model metrics were not changed.
2. **Docker/PostgreSQL verification.** Docker Desktop was launched in the
   background, but the Linux engine pipe remained unavailable even outside the
   sandbox. Live application checks and database integration checks therefore
   remain unverified. Most skipped tests require an explicitly configured test
   PostgreSQL instance. Any eventual test database must be separate from the
   application's real database.
3. **Frontend payload size.** The build succeeds with an existing warning about
   its approximately 860 kB JavaScript bundle before gzip (245 kB gzipped).
   Route-based loading is a possible follow-up; it was not implemented here.

These results describe this local run, not a production security certification
or validation of the model for Pakistani SME lending.
