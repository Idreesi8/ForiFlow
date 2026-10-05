# Changelog

All notable changes to ForiFlow are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versioning follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.9.0] - 2026-10-05

### Added

- **Group audit of the model.** `python -m ml.fairness_audit` takes the same
  20% hold-out as the evaluation, joins each loan to four attributes of the
  public file that the model never reads (age, income, housing, loan purpose)
  and records, per group: the approval rate and its ratio to the best group
  (the four-fifths screen), the model's probability of default against the
  default rate the group really had, good payers rejected and defaulters
  approved. Served at `GET /model/fairness` and shown on the Model Performance
  page. Findings on the 6,517 hold-out loans:
  - Age: every age band is priced in line with its outcome (largest gap 1.7
    points). Under-25s are approved at 0.66 of the rate of the 45-and-over
    band, and they do default more (23.4% against 20.5%).
  - Housing: the largest mispricing. Outright owners are given 24.5% and
    defaulted 8.1%; renters are given 24.3% and defaulted 31.2%. The model has
    no input for assets or collateral.
  - Income: the lowest quarter is approved at 0.22 of the top quarter's rate,
    yet the model is lenient to it (30.8% given, 39.6% defaulted) and harsh to
    the top quarter (14.5% given, 9.1% defaulted).
  - Loan purpose: business-venture loans are given 21.6% and defaulted 14.6%.
  The file has no gender, region, religion or ethnicity, so none of those is
  audited, and these are consumer loans, not Pakistani SMEs. Nothing in the
  audit changes the model.
- **Approval authority by facility size.** A manager may approve a Manual
  Review facility up to `MANAGER_APPROVAL_LIMIT_PKR` (default 2,000,000, a
  policy figure the lender sets); above it only an admin may approve, and the
  API answers `403` naming both amounts. A manager can still reject at any
  size. Every application now reports `approval_authority` and
  `manager_approval_limit_pkr`, and the decision panel disables Approve and
  says why.

## [1.8.0] - 2026-10-05

### Added

- **Population drift monitor.** `GET /model/drift` compares every stored
  application with the population the model was trained on, using the
  Population Stability Index for the score and for each model input (facility
  size against turnover, repayment history, years in operation). Inputs are
  rebuilt exactly as scoring builds them. Each figure comes with the PSI that
  chance alone would give at that sample size, about (bins - 1) / rows, and no
  verdict is given below 100 applications. `ml.evaluate_model` records the
  reference distributions. The Model Performance page shows training against
  live shares bin by bin.
- **Credit memo.** A printable page per application (`/memo/{id}` in the
  dashboard, linked from the decision panel): the request, score, probability
  of default, each factor's points, path to approval, where the turnover came
  from, and who decided and why. Read from the stored record only.

### Fixed

- **Scoring failed with a 500 for some applicants (1.5.0 to 1.7.1).** When
  neither a smaller facility nor a higher turnover could move an applicant
  into a better band, for example a Manual Review case with an adverse
  repayment record and under a year of trading, the path-to-approval search
  had nothing left to score on its second pass and raised. The assessment
  was not saved. It now returns the empty path and names what blocks it. A
  regression test pins that applicant, and a seeded test scores 300 applicants
  across the extremes of every input and checks each reported threshold.

## [1.7.1] - 2026-10-04

### Fixed

- The frontend image build retries `npm ci` once. On Docker Desktop the
  esbuild install step can fail with `ETXTBSY` ("text file busy"), which
  stopped the 1.7.0 rebuild; it is a timing fault and a clean retry passes.

## [1.7.0] - 2026-10-04

### Added

- **Turnover from a statement.** `POST /score/statement` reads a wallet or bank
  statement CSV and returns the median monthly inflow and net cash flow over
  full calendar months, how much the inflows vary, and warnings to check by
  hand (one inflow above 25% of the total, months with more out than in,
  failed or unreadable rows). The scoring form fills digital payments, cash
  flow and order consistency from it. When the statement is sent with the
  application, the API re-reads it and stores the summary as
  `turnover_evidence`, with `matches_statement` false if a figure was changed
  afterwards. Raw transactions are not kept. The parser matches common column
  names; it does not compute a repayment-history score, which the model reads
  as a bureau record. `docs/samples/` has a synthetic statement for demos.
- **Manager role.** Three roles, each including the one below: `analyst`
  (score, monitor, take alerts), `manager` (also decide Manual Review cases
  and resolve alerts), `admin` (also manage officer accounts). Existing
  accounts keep their role. A Team & Roles page lets an admin list and create
  accounts.
- **Payment reminders.** `GET /portfolio/reminders` lists installments that
  are overdue, due within 7 days, or unpaid from earlier months, with a
  drafted message in English and Roman Urdu. The schedule runs monthly from
  the approval date; an installment is cleared once its month is recorded.
  The Reminders page copies the message or opens it in WhatsApp when the
  application carries the optional `contact_phone`. ForiFlow sends nothing.
- Migration `0005_roles_and_evidence`: widens the role check, adds nullable
  `turnover_evidence_json` and `contact_phone`.

### Fixed

- Comments on the fallback engine's weights and bounds claimed they were
  agreed with a credit policy team and calibrated on a reference portfolio.
  They were set by hand; the comments now say so.

## [1.6.0] - 2026-10-04

### Added

- **Early-warning Markov chain.** `python -m ml.ews_markov` fits monthly
  transitions between Current, Late 1-59, Late 60-89 and Default on the UCI
  "Default of Credit Card Clients" file (30,000 accounts, six months each),
  using 24,000 accounts to fit and 6,000 to check, and writes
  `ml/ews_transition.json`. Monitoring now returns `default_probability_3m`
  (0.09%, 2.66% and 30.07% for the three live states) and takes
  `estimated_days_to_default` from the chain (246, 160 and 54 days; the mean
  time to Default given it happens within 12 months). An alert is raised at
  10% or more, or on the existing drop of more than 15 points, which still
  carries the bureau and POS signals.
- The script also records how the chain does on unseen accounts and against
  a second-order chain, a logistic hazard model and gradient boosting. The
  hazard models rank better (AUC 0.915 and 0.921 against 0.855) but need
  inputs with no clean counterpart on a term loan, so they are not served.
- `GET /model/early-warning`, and an Early-warning model section on the Model
  Performance page: transition matrix, outlook per state, hold-out check,
  alternatives.

### Changed

- `estimated_days_to_default` no longer comes from the hand-set runway table
  when the chain is loaded: a Late 60-89 month reports 54 days, not 12 to 45.
  The rule-based estimate remains as the fallback (`runway_basis: "rules"`).
- The chain is fitted on consumer card accounts in Taiwan in 2005, not on
  Pakistani SME loans; the API, the screens and the risk register say so.

## [1.5.0] - 2026-10-04

### Added

- **Path to approval.** For a Rejected or Manual Review outcome the trained
  ensemble reports the largest facility (rounded down to PKR 1,000) and the
  smallest evidenced monthly turnover (rounded up) at which the same applicant
  reaches Manual Review and Approved. Both members carry monotone constraints,
  so each crossing point is unique; three batched grid passes find it in about
  60 ms and the result is re-scored after rounding. When no facility size
  reaches a band, the factors holding it back are named. Stored with the
  explanation as `approval_path` and shown under the SHAP report and the
  scoring result. It is a model output for the officer, not an offer.
- **Loan book analytics.** `GET /portfolio/summary` reports disbursed, due,
  collected, overdue and outstanding amounts, the collection rate, portfolio
  at risk (outstanding 30 or more days late in the latest month), defaulted
  facilities, the model-band by final-outcome decision matrix, and a table
  per business sector. The dashboard shows it as a Loan book section.
  Installments are straight-line (facility / tenure): ForiFlow holds no
  interest rate. Months without a recorded amount are counted and left out
  of the collection figures, never estimated.
- Applications take an optional `business_sector` (reporting only, the model
  does not read it) and `POST /ews/monitor` an optional `amount_paid_pkr`.
  Migration `0004_portfolio_fields` adds both columns as nullable.
- `docs/risk-register.md`: model, data, process and security risks, what
  ForiFlow does about each today and what a bank would still need.
- `ml.evaluate_model` records the Spearman correlation between the model's
  features (largest 0.055 in absolute value).

### Changed

- The calibrator is fitted over bins of 250 loans, so it never reports a
  probability of exactly 0% or 100% from a handful of loans. Hold-out Brier
  0.1302, expected calibration error 0.0091.

## [1.4.0] - 2026-10-03

### Added

- **Calibrated probability of default.** `python -m ml.evaluate_model` fits an
  isotonic regression on out-of-fold predictions of the training part and
  stores its breakpoints in `ml/model_evaluation.json`. Every score now returns
  `probability_of_default`, and it is saved inside the stored explanation. On
  the hold-out the Brier score falls from 0.1852 (worse than the 0.1706 of
  always predicting the base rate) to 0.1305, and the mean prediction from
  44.4% to 21.9% against 21.8% observed. The calibrator is monotone, so the
  score, the policy bands and the SHAP values are unchanged. It is calibrated
  to the public training file, not to a Pakistani SME portfolio, and it is
  ignored if it belongs to another training run.
- **Hold-out evaluation.** The same script records the ROC curve, the
  confusion matrix, a threshold table (score 30 to 70), reliability bins and
  the default rate inside each policy band (Rejected 59.5%, Manual Review
  14.6%, Approved 8.4%), all for the served model on the 6,517 hold-out loans.
- `GET /model/evaluation` and `GET /model/comparison` serve those results and
  the alternatives benchmark.
- **Model Performance page** in the dashboard: ROC curve, calibration chart,
  confusion matrix, threshold table, default rate by band, and the six-model
  comparison with paired t-tests. The scoring result and the SHAP report show
  the probability of default beside the score.

## [1.3.0] - 2026-09-29

### Added

- **Officer decision on Manual Review.** `POST /score/applications/{id}/review`
  (admin) approves or rejects a 41–70 case with a reason of at least 10
  characters, recording who and when. The model's band stays in `decision`;
  `final_decision` combines the two and is `null` while the review is
  pending. A recorded decision cannot be changed (`409`). The dashboard shows
  the decision panel under the SHAP report and after scoring, the register
  has a Final decision column, a Pending review filter and a Review action,
  and the approval rate and approved exposure count officer approvals.
- Every assessment records the officer who scored it (`scored_by`).
- EWS alerts can be taken for review by any officer (`PATCH
  /ews/alerts/{id}/review`, status In Review with the officer's name).
  Resolving now needs a note and records who resolved it; a resolved alert
  cannot be resolved again (`409`). Alerts carry the borrower's business name.
- Migration `0003_officer_decisions` adds the columns (all nullable, so
  existing rows are kept as they are).
- `GET /score/stats`: portfolio totals computed in SQL over every row (counts
  per model band, pending reviews, final approvals and rejections, approved
  exposure, average score, score histogram, open alerts). The dashboard KPIs
  and charts use it, so they are no longer limited to the newest 200 rows.
- `GET /score/applications?final_decision=Approved|Rejected`; the monitoring
  form lists approved facilities through it.
- `show-data.bat` / `scripts/show-data.sql`: read-only view of what PostgreSQL
  stores (latest applications and their SHAP explanations, officer decisions
  on Manual Review cases, EWS records, alerts, hashed officer accounts) and
  which Docker volume holds it.
- `python -m ml.compare_models` benchmarks the served ensemble against logistic
  regression, XGBoost alone, Random Forest alone, LightGBM and an MLP under the
  production CV protocol, writing `ml/model_comparison.json`. The results and
  what they mean are in `backend/README.md`.

### Changed

- Only an approved facility can be monitored: a Manual Review case must be
  approved by an officer first (before, any Manual Review application could be
  monitored without a decision). Officer-rejected cases return `409` like
  model-rejected ones.
- `POST /explain/{id}?refresh=true` no longer overwrites the explanation stored
  at scoring time, which is the audit record; it returns the recomputed one.
- EWS alerts follow the latest month on file: back-filling an older month no
  longer rewrites the open alert, and correcting the latest month so it no
  longer breaches closes the alert with an automatic note.
- `POST /ews/monitor` refuses a month past the facility's tenure (`422`).
- Taking an alert that another officer is reviewing returns `409` instead of
  silently reassigning it.
- Version 1.3.0 (API, dashboard footer, Docker image tags).

### Fixed

- Dashboard: the open-alert count and alert panel were worked out from the 5
  worst alerts including resolved ones, so they could show 0 while an alert was
  open; the score histogram dropped scores between whole-number edges (e.g.
  40.5, 70.3).
- Monitoring form: bureau balance and POS inflow no longer reject amounts that
  are not multiples of 10,000.
- The SHAP chart shows the facility ratio as a percentage of annual turnover
  instead of a bare number.
- The decision panel reloads when another officer decided first (`409`).
- Docs: endpoint tables, configuration, layout, deployment diagram (PostgreSQL
  service and volume), migration list and contributor guidance brought in line
  with the code; README screenshots recaptured from 1.3.0.
- `start.ps1` / `rebuild.bat` could report "docker compose up failed" after a
  successful start when the console was redirected, because compose's stdout
  was captured together with the exit code.
- The root README no longer lists JWT authentication and PostgreSQL as roadmap
  items (both shipped in 1.1.0), describes the EWS as the rule-based check it
  is, and reports the measured scoring latency.

## [1.2.0] - 2026-09-25

### Fixed

- A fresh clone now serves the trained ensemble: the four model artefacts are
  committed (only the training log and raw Kaggle CSVs stay ignored).
- `python -m ml.train_real_model --dataset credit_risk_shared` no longer needs
  `Loan_default.csv`; it reads only the file the chosen dataset uses.
- scikit-learn and xgboost are pinned to the versions the artefacts were
  pickled with (1.8.0 and 3.4.0), removing the version-mismatch warnings.
  The backend moves to Python 3.12 (xgboost 3.4 requires it).
- The pickled SHAP link function carried Python 3.14 bytecode and crashed when
  called on the 3.12 image; it is now rebound on load. Scores are unchanged.
- Payment history between 53 and 79 no longer lands on an untrained third
  plateau: serving reads 0-52 as adverse and 53-100 as clean, matching the
  binary flag the model was trained on.
- `POST /ews/monitor` refuses Rejected applications (`409`).
- The backend image installs `xgboost-cpu` (same 3.4.0 library) instead of
  `xgboost`, whose Linux wheel pulls in a ~350 MB `nvidia-nccl` GPU library
  that ForiFlow never uses; the rebuild on a slow connection stalled on it.

### Added

- Role enforcement: resolving an EWS alert and managing accounts are
  admin-only (`403` for analysts); the role is read from the database.
- `GET /auth/me`, `GET /auth/users`, `POST /auth/users`.
- `JWT_SECRET_KEY` must be 32+ characters and not the placeholder; new
  passwords must be 12+ characters.
- CI runs on every branch: backend tests (in-memory SQLite, plus parity tests
  against a PostgreSQL 16 service) with both the surrogate and the trained
  model, plus a frontend production build.
- Intake form: explains how history is read and warns when a facility exceeds
  30% of estimated annual turnover.
- `backend/README.md`: training-data sources with checksums, and measured
  model limitations.
- `docs/screenshots/` recaptured from the rebuilt 1.2.0 stack, and the FYP
  proposal (v2.5) restated for the monotone model, roles and CI.

### Changed

- **Model retrained with a monotone random forest.** Both ensemble members now
  carry the same monotone constraints, so more years in operation, a stronger
  repayment record or a smaller facility can never lower a score (before, six
  years scored 10.6 points below five). Full candidate bake-off re-run; the
  winner is unchanged. CV AUC 0.7758 → 0.7752, hold-out 0.7756 → 0.7731,
  Brier 0.175 → 0.185. Hold-out policy mix moves from 19.5 / 41.7 / 38.8 % to
  18.6 / 63.5 / 18.0 % (Rejected / Manual Review / Approved). Every score
  changes; Khan Traders goes from 64.87 to 56.68 (still Manual Review). The
  forest shrinks from 86,709 to 4,477 leaves (model file 13.9 MB → 1.1 MB).
- The compliance note reads its AUC figures from the artefact metadata instead
  of a hard-coded string.
- React Router 6 → 7.18 and Vite 5 → 6.4 (`npm audit`: 0 vulnerabilities).
- README problem statement: unsourced statistics removed; the SBP line now
  cites what has actually been reported.

### Removed

- Unrouted `PosterPage.jsx` and `ForiFlowPoster.jsx`.
- The superseded HTML poster (`docs/foriflow-poster.html` / `.png`) and its
  renderer; `Claude outputs/` (local poster iterations) is no longer tracked.

## [1.1.0] - 2026-09-19

### Added

- PostgreSQL 16 with Alembic migrations, replacing the SQLite volume.
- On-premise JWT login (HS256, 8 hours) with a seeded admin account and
  password rotation.
- `start.bat` / `start.ps1` everyday start (starts Docker Desktop if needed)
  and a desktop shortcut; API, dashboard and PostgreSQL bound to 127.0.0.1.
- Deployment guide for PostgreSQL and JWT; FYP poster and proposal.

### Changed

- Stopped claiming SBP compliance or a live ECIB feed; intake fields the
  model does not use are labelled.
- One published AUC figure, with the public-proxy dataset caveat.
- SHAP summary cards round so they add up to the displayed score; EWS
  filters stay accurate after resolving an alert.

## [1.0.0] - 2026-08-15

### Added

- Initial release
- FastAPI backend with an XGBoost + Random Forest soft-voting ensemble
- React 18 officer dashboard (Vite, Tailwind CSS, Recharts)
- SHAP TreeExplainer integration on every `/score` and `/explain` response
- Early Warning System: monthly re-score and alert on a drop greater than 15 points
- Docker Compose stack (backend :8000, nginx dashboard :3000, SQLite volume)
- Public documentation, GitHub templates, LinkedIn launch copy, and screenshot automation

