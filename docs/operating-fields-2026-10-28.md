# Operational use and dataset research for additional fields

28 October 2026, Pakistan time.

Tenure, existing debt, inventory turnover, order consistency and headcount now
have functional operating checks on the intake form, its unsaved review, and
saved-case review. Their values previously did not affect the serving ML score.
That score still uses its existing three-feature contract; this update does not
claim that the five fields have acquired learned default-risk effects.

## What the fields do

| Field | Active use | Limit |
| --- | --- | --- |
| Tenure | New principal per month; comparison with typed cash flow | Principal only, excluding interest and fees |
| Existing debt | Outstanding balance divided by annual typed cash flow | Balance is not a repayment schedule or monthly debt service |
| Inventory turnover | Implied cycle, 365 divided by annual turns | Depends on the entered inventory convention; no universal sector threshold |
| Order consistency | Entered estimate compared with a reparsed statement receipts-stability proxy | Receipts are not orders; an order ledger is needed to verify orders |
| Employees | Monthly digital receipts per person, including owners | Descriptive; not total revenue, productivity, or a credit penalty |

Zero denominators and ratios outside finite precision are withheld. Missing
figures are not converted to zero. Every calculation names its formula and
limitations. There is no weighted score, risk band or approval rule in these
checks. Existing credit policy and officer authority remain unchanged.

`POST /model/operating-checks` accepts eight numeric figures and an optional CSV,
rejecting identity, contact and forged reference fields. It reparses the attached
CSV on the backend and echoes only the numeric figures, derived checks and source
fingerprint. It never echoes raw CSV, runs credit inference or persists a case.
`GET /model/applications/{id}/operating-checks` uses that case's recorded figures;
the checks are calculated now, separately from the stored score. All routes are
authenticated; numerical responses use `Cache-Control: no-store`.

The frontend cancels superseded requests, withholds results after edits and
rejects a mismatched case, numeric echo, source fingerprint, or malformed result.
Saved-case responses must match the requested case and its displayed amount and
term. Failure retains entries. No check automatically submits an assessment.

## Acquired data and semantic fit

Raw research copies are in `.local/datasets/sme-field-research/`, outside Git and
the serving image. No borrower records were uploaded to a data provider.
The reproducible, non-executing inspection produces
`backend/ml/sme_field_research.json`; the authenticated research endpoint and
Model page expose its provenance, checksums, field coverage and remaining gaps.

| Source | Actually acquired | What it supports and what blocks training |
| --- | --- | --- |
| [Bangladesh SME research, Zenodo v2](https://zenodo.org/records/20560302) | Checksum-verified archive; 1,200 CSV records | Preferred tenure and employee counts are candidates. Existing loans is only Yes/No; there is no exact outstanding-debt, inventory or order field. Cash-flow stability is a 1–5 rating. The target describes past missed payments; prospective outcome timing is unresolved. |
| [UCI Polish Companies Bankruptcy](https://archive.ics.uci.edu/dataset/365/polish+companies+bankruptcy+data) | Five ARFF files: 7,027 / 10,173 / 10,503 / 9,792 / 5,910 rows | Inventory and liabilities ratios are research material. Definitions and bankruptcy horizons differ from the intake fields and facility default. Files were not pooled or treated as distinct companies. |
| [Pakistan World Bank Enterprise Survey 2022](https://microdata.worldbank.org/catalog/6461) | Official metadata for 1,300 catalogue cases and 434 variables | Pakistan business context, employment and finance. Firm-level microdata was not acquired. Survey population/weights and headcount definitions need care; a prospective repayment outcome was not established. |
| [US SBA 7(a)/504 FOIA](https://data.sba.gov/dataset/7a-504-foia) | Official XLSX dictionary; loan records not acquired | Loan term is documented. Jobs supported combines created/retained jobs and cannot be substituted for present headcount. Current outcomes require cohort/censoring design; EXEMPT is not a non-default label. |

The Bangladesh `missed_payment_last_12m` column exactly duplicates the binary
target in all 1,200 rows. Using it as a predictor would leak the answer. It was
identified and excluded from any proposed predictor set; no predictive model was
fitted. Publisher claims of data collection or accuracy were not independently
validated or adopted as ForiFlow results. No downloaded scripts/notebooks ran.

**Training readiness remains false.** No acquired source supplies all five exact
measures with a properly timed, prospective Pakistani SME default outcome. The
next model needs application-time definitions, borrower-separated/time-based
evaluation, fixed outcome windows, reliable repayment labels and calibration.
No weights, synthetic replacements, cross-dataset row joins or fabricated labels
were introduced to conceal those gaps.

## Attribution and reproducibility

- Chowdhury, S., Das, A. and Paul, S. (2026), *AI-Driven Credit Risk Assessment for
  Bangladesh SMEs: Dataset and Analysis Code*, v2.0. [DOI 10.5281/zenodo.20560302](https://doi.org/10.5281/zenodo.20560302).
  Data: CC BY 4.0; code: MIT. Only the CSV was inspected; profiles are ForiFlow's
  derived summaries, and the source archive is retained unchanged.
- Tomczak, S. (2016), *Polish Companies Bankruptcy*, UCI Machine Learning
  Repository. [DOI 10.24432/C5F600](https://doi.org/10.24432/C5F600).
  CC BY 4.0. Cohort counts and fit notes are ForiFlow's derived summaries.
- World Bank Group, *Pakistan World Bank Enterprise Survey 2022*, reference
  PAK_2022_WBES_v01_M; metadata consulted/downloaded 28 October 2026. Microdata
  access and licence terms are specified by its external Enterprise Surveys
  distributor; metadata access does not grant unrestricted microdata use.
- U.S. Small Business Administration, *7(a) & 504 FOIA Data Dictionary*;
  consulted/downloaded 28 October 2026. Publisher licence: U.S. Government Works.

Run `python scripts/fetch_sme_datasets.py`, then
`python scripts/audit_sme_datasets.py` from the project root. The downloader caps
file sizes and download time, verifies cached SHA-256 values and the Bangladesh
publisher checksum, and does not execute publisher code. The auditor reads data
archives and dictionaries directly and records concrete schema/label gaps.

## Verification

- 49 new operating/backend checks passed on Windows and in the final Linux image.
  The Linux run had no network, no pilot credentials/volumes and a read-only root.
- 39 existing numerical-input checks and two trained feature/score contract
  checks passed on Windows: 90 distinct focused backend checks in total.
- All 80 frontend unit checks passed. Production frontend and final Docker
  backend/frontend builds passed. The full backend suite was not rerun.
- Browser evidence and deployment snapshots are retained in
  `archive/operating-fields-2026-10-28/`. QA uses a disposable SQLite database,
  synthetic account and case, actual API calculations/statement parsing and
  controlled delays, failure and mismatched-response injection.

Twenty browser scenarios passed, including numeric-only live checks, field edit
invalidation, delayed/failing/mismatched responses, explicit retry, reparsed
statement comparison, zero denominators, review-stage checks, saved synthetic
and historical cases, research-source details, 1440px/390px reflow, keyboard
access and clearing incomplete inputs. The QA log recorded 66 requests with no
unexpected mutation endpoints and no score or decision submissions. No live
assessment was submitted; verification figures were cleared.

Both services are deployed and all three main containers are healthy. Production
readiness reports the ML engine serving. All ten table fingerprints and all six
credit/anomaly artefact hashes match their pre-deployment values. Backend and
frontend image identities changed; the database image did not. Rollback tags and
a custom-format dump were preserved before building. `pg_restore --list`
verified archive readability; this was not a new scratch restore exercise.
Temporary QA API/preview processes were stopped and the live tab was left on a
clean scoring form. Screenshots and keyboard checks are not WCAG certification.
