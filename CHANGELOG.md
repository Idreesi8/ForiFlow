# Changelog

All notable changes to ForiFlow are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versioning follows
[Semantic Versioning](https://semver.org/).

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
  binary flag the model was trained on. Scores at 80+ and 52- are unchanged.
- `POST /ews/monitor` refuses Rejected applications (`409`).

### Added

- Role enforcement: resolving an EWS alert and managing accounts are
  admin-only (`403` for analysts); the role is read from the database.
- `GET /auth/me`, `GET /auth/users`, `POST /auth/users`.
- `JWT_SECRET_KEY` must be 32+ characters and not the placeholder; new
  passwords must be 12+ characters.
- CI runs on every branch: backend tests on PostgreSQL 16 with both the
  surrogate and the trained model, plus a frontend production build.
- Intake form: explains how history is read and warns when a facility exceeds
  30% of estimated annual turnover.
- `backend/README.md`: training-data sources with checksums, and measured
  model limitations.

### Changed

- React Router 6 → 7.18 and Vite 5 → 6.4 (`npm audit`: 0 vulnerabilities).
- README problem statement: unsourced statistics removed; the SBP line now
  cites what has actually been reported.

### Removed

- Unrouted `PosterPage.jsx` and `ForiFlowPoster.jsx`.

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

