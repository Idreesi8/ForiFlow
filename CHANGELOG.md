# Changelog

All notable changes to ForiFlow are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versioning follows
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-08-15

### Added

- Initial release
- FastAPI backend with an XGBoost + Random Forest soft-voting ensemble
- React 18 officer dashboard (Vite, Tailwind CSS, Recharts)
- SHAP TreeExplainer integration on every `/score` and `/explain` response
- Early Warning System: monthly re-score and alert on a drop greater than 15 points
- Docker Compose stack (backend :8000, nginx dashboard :3000, SQLite volume)
- Public documentation, GitHub templates, LinkedIn launch copy, and screenshot automation

[1.0.0]: https://github.com/Idreesi8/foriflow/releases/tag/v1.0.0
