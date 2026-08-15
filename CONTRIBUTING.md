# Contributing to ForiFlow

Thank you for helping improve credit intelligence for Pakistani SMEs. This
document is the shortest path from a clone to a reviewable pull request.

## How to contribute

1. Fork the repository and clone your fork.
2. Create a branch from `main` using the naming convention below.
3. Make a focused change. Keep ML, API and UI work in separate PRs when you can.
4. Run the checks that apply to your change (see below).
5. Open a pull request against `main` using the template in
   `.github/PULL_REQUEST_TEMPLATE.md`.

Issues are welcome. Use the bug or feature templates so a reviewer can
reproduce the problem or understand the proposal without a follow-up thread.

## Local setup

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev
```

The dashboard is at http://localhost:3000. Vite proxies `/api` to the API.

Docker is the demo path: `docker compose up --build -d` from the repository
root. See [docs/deployment.md](docs/deployment.md).

## Code style

| Language | Tool | Rule of thumb |
|----------|------|----------------|
| Python | [Black](https://black.readthedocs.io) (line length 88) plus the existing type hints and docstrings | Match `backend/services/` and `backend/routers/` |
| JavaScript / JSX | [Prettier](https://prettier.io) defaults | Functional components, hooks, no unused imports |
| Markdown | Wrap prose near 80 columns | No trailing whitespace |

Do not reformat files you did not otherwise change.

## Tests

From `backend/`:

```bash
pytest
```

API tests pin the linear surrogate so they stay deterministic. ML contract
tests in `tests/test_ml_model.py` load the trained artefacts and skip when
those files are absent. After a model retrain, run that file explicitly.

There is no frontend unit suite yet. If you change the dashboard, say what you
clicked in the PR and attach a screenshot when the UI changes.

## Branch naming

| Prefix | Use for |
|--------|---------|
| `feature/` | New behaviour (example: `feature/jwt-rbac`) |
| `bugfix/` | A defect with a failing case (example: `bugfix/cors-preflight`) |
| `docs/` | Documentation only (example: `docs/api-ews-examples`) |

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org):

```
<type>(<optional scope>): <imperative summary>

Optional body explaining why, not what.
```

Types we use: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`.

Examples:

```
feat(ews): alert when a monthly score drops more than 15 points
fix(scoring): clip loan_to_income before the ensemble sees it
docs(api): add /ews/monitor request examples
```

Keep the subject under 72 characters. Do not mention tool names or "AI" in the
subject; describe the change a reviewer will read in `git log`.

## What not to commit

- `backend/ml/*.pkl` and raw CSVs under `backend/ml/data/` (see `.gitignore`)
- Local SQLite files, `.env`, and `node_modules`
- Screenshots of customer or bank data

Trained artefacts are produced by `python -m ml.train_real_model`. Do not
check them in unless a maintainer asks you to.

## Review bar

A PR should:

- Stay inside one concern
- Include tests when it changes scoring, EWS or an HTTP contract
- Leave the surrogate fallback working if artefacts are missing
- Avoid claiming SBP certification — ForiFlow is built to *support* an audit,
  not to replace a bank's model-risk function
