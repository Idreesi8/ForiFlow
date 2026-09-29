# Changelog

All notable changes to ForiFlow are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versioning follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

