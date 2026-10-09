# ForiFlow security

**ForiFlow is intended for controlled pilot deployment and has not undergone an
independent penetration test or formal security certification.**

It makes no claim of PCI DSS, ISO 27001, SOC 2 or SBP compliance or
certification. What follows is the security baseline as of release 2.3.0:
what is enforced, how to configure it, and what is still missing.

Contents: [architecture](#1-security-architecture) ·
[authentication and sessions](#2-authentication-and-sessions) ·
[roles (RBAC)](#3-roles-rbac-matrix) · [data protection](#4-data-protection) ·
[API hardening](#5-api-hardening) · [configuration](#6-configuration-development-vs-production) ·
[secrets](#7-secret-management) · [database, backup, restore, migrations](#8-database-backup-restore-and-migrations) ·
[health](#9-health-and-readiness) · [audit trail](#10-audit-trail) ·
[dependencies and containers](#11-dependencies-and-containers) ·
[limitations](#12-known-limitations) · [reporting](#13-reporting-a-problem)

## 1. Security architecture

```
browser ──> nginx :3000 (127.0.0.1 only, non-root)
              ├── /          dashboard (CSP, no-sniff, frame-deny)
              └── /api/* ──> FastAPI :8000 (non-root, no capabilities)
                               ├── body size limit, security headers, request id
                               ├── JWT check on every request (signature, expiry,
                               │   issuer, revocation, account enabled)
                               ├── role check per route (analyst / manager / admin)
                               └── PostgreSQL 16 (127.0.0.1 only; audit_logs append-only)
```

Every port is bound to 127.0.0.1: the pilot stack is not reachable from the
network. The dashboard and the API share one origin, so the browser never
makes a cross-origin call. Security decisions are made by the API; the
dashboard hiding a button is a convenience, never the control.

## 2. Authentication and sessions

| Control | Behaviour |
|---|---|
| Password storage | bcrypt, cost 12 (passlib). Hashes are never returned by any endpoint or written to logs or the audit trail. |
| Password rule (when a password is **set**: new account, seed script) | 12 to 72 characters (72 bytes is bcrypt's limit; longer is refused, not truncated). Refused: the `.env.example` placeholder, fewer than 5 different characters, keyboard/number sequences, common passwords (after removing digits and symbols, e.g. `Password123!`), and anything containing the username. No composition recipe (NIST SP 800-63B). Sign-in does not re-check the rule, so an older account still signs in. |
| Wrong credentials | One answer for an unknown username and a wrong password: `401 Incorrect username or password`. An unknown username costs the same bcrypt time as a known one. |
| Lockout | 5 wrong passwords for one username within 15 minutes lock that username for 15 minutes (`429`, `Retry-After`). Unknown usernames lock the same way, so the lock does not reveal which accounts exist. The lock lifts by itself; nothing is locked permanently. A correct sign-in clears the count. Stored in the database (`login_attempts`), so it survives a restart. |
| Rate limit | 30 sign-in requests per 5 minutes per client address (`429`). Kept in the API process: it resets on restart and is per worker (the Docker stack runs one). |
| Token | HS256 JWT with `sub`, `role`, `iat`, `exp`, `iss=foriflow` and a random `jti`. All claims are required. `alg=none`, other issuers, other keys, expired tokens and pre-2.3 tokens are refused. Lifetime `FORIFLOW_JWT_EXPIRE_MINUTES` (default 480 = 8 hours, allowed 15 to 720). The role inside the token is not trusted: it is re-read from the database on every request. |
| Sign-out | `POST /auth/logout` revokes that token's `jti` (`revoked_tokens`) until it would have expired. Other sessions of the same officer stay valid. The dashboard calls it on "Sign out". |
| Disabled accounts | An admin disables or re-enables an account (`PATCH /auth/users/{id}/status`, Team & Roles page). A disabled account's tokens stop working on the next request; sign-in with the correct password gets `403 This account is disabled`; a wrong password still gets the ordinary `401`. Accounts are never deleted. An admin cannot disable their own account or the last enabled admin. |
| Session storage in the browser | The token is kept in `localStorage`. Any script running in the page could read it; the strict Content-Security-Policy (no inline or third-party script) is the mitigation. On any `401` the dashboard drops the token and returns to the sign-in page ("Your session has ended"). |

## 3. Roles (RBAC) matrix

Enforced by the API on every request. The matrix below is checked by
`backend/tests/test_security.py`, which reads the role rule off every route,
so a new route without its check fails the suite.

| Action | Analyst | Manager | Admin |
|---|:---:|:---:|:---:|
| Sign in, sign out, `GET /auth/me` | ✓ | ✓ | ✓ |
| Score an application, summarise a statement, read applications, explanations, SHAP | ✓ | ✓ | ✓ |
| Register a borrower; read borrowers and borrower history | ✓ | ✓ | ✓ |
| Record a monthly EWS observation (no score override) | ✓ | ✓ | ✓ |
| Read EWS overview, trends, alerts, alert history, portfolio, reminders, model pages, active policy | ✓ | ✓ | ✓ |
| Approve / reject / escalate a credit decision; review | ✗ | ✓ (up to the policy's manager limit; not against a Decline recommendation if the policy says admin-only) | ✓ |
| Override an EWS score; correct an observation | ✗ | ✓ | ✓ |
| Acknowledge / assign / set due date / action required / resolve / dismiss an alert | ✗ | ✓ | ✓ |
| Correct a borrower record (`PATCH /borrowers/{ref}`) | ✗ | ✓ | ✓ |
| Create or activate a credit policy version | ✗ | ✗ | ✓ |
| Read the audit trail | ✗ | ✗ | ✓ |
| List, create, disable, re-enable officer accounts | ✗ | ✗ | ✓ |

**Guessed ids (IDOR/BOLA).** Every mutating route checks the role before it
looks at the id, so guessing an application, alert, observation or borrower
id gives an analyst `403`, not access. Unknown ids give `404` with no internal
detail. ForiFlow is single-lender with no branch scoping: **every signed-in
officer can read the whole portfolio by design.** Borrower references
(`BRW-000012`) are sequential and therefore guessable; that grants nothing an
officer could not already list. Branch- or team-level scoping is not
implemented (see §12).

## 4. Data protection

- CNIC/NTN are never returned in full: responses carry `identifier_masked`
  (last four digits). They are never accepted in a URL (so never in access
  logs) and are masked in the audit trail. `422` validation errors redact
  `password` and `borrower_identifier` instead of echoing them.
- Phone numbers are masked in the list endpoints (`GET /score/applications`,
  `GET /borrowers`, 2.3). The full number stays on the borrower and
  application records and on the Reminders page, where an officer uses it.
- Passwords, tokens, `Authorization` headers, cookies and anything named like
  a secret are replaced by `[redacted]` before an audit entry is written.
  Sign-in and sign-out entries record a `session_id` (the token's `jti`), never
  the token.
- Unexpected errors return `500 {"detail": "Internal server error…",
  "request_id": "…"}`; the traceback goes only to the server log, under the
  same request id. Database errors return `503` without SQL.
- API responses carry `Cache-Control: no-store`, so borrower data is not kept
  by a shared browser cache or proxy.
- Data at rest is not encrypted by ForiFlow; use disk encryption (BitLocker)
  on the laptop and encrypt backups (see §8).

## 5. API hardening

| Control | Setting |
|---|---|
| Security headers (API) | `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'…`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`, `Cross-Origin-Resource-Policy`, `Cache-Control: no-store`; `Strict-Transport-Security` when the request arrived over HTTPS. No `Server` header. |
| Security headers (dashboard, nginx) | CSP `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'…`, plus the same no-sniff / frame / referrer / permissions headers; `server_tokens off`. `'unsafe-inline'` styles are needed by the chart library. |
| Body size | 3 MiB in the API (`413`), 4 MiB in nginx. A malformed `Content-Length` is `400`. Schemas cap every string (e.g. statement CSV 2,000,000 characters). |
| CORS | `FORIFLOW_CORS_ORIGINS` (comma separated). Unset: closed in production (same-origin stack), dev-server origins in development. `*` is refused in every mode. No credentials mode (the token is a header, not a cookie). |
| Interactive docs | `/docs`, `/redoc`, `/openapi.json`: on in development, **off in production** unless `FORIFLOW_ENABLE_DOCS=true` (then a warning is logged at start-up). OpenAPI support itself is kept. |
| Validation | Pydantic schemas on every input; unknown enum values, out-of-range numbers and over-long strings are `422`. |
| Rate limiting | Sign-in only (§2). Other endpoints are behind authentication and are not rate limited. |

## 6. Configuration: development vs production

`FORIFLOW_ENV` = `development` (default for a local `uvicorn` run) or
`production` (set by `docker-compose.yml`). Any other value stops the API.

| | development | production |
|---|---|---|
| Unsafe configuration (below) | logged as warnings; starts | **refuses to start**, naming each setting (never its value) |
| `/docs`, `/redoc`, `/openapi.json` | on | off unless `FORIFLOW_ENABLE_DOCS=true` |
| CORS default | localhost dev-server origins | none |
| Database | SQLite allowed | PostgreSQL required |

Production refuses to start when: `JWT_SECRET_KEY` is missing, the
placeholder, or under 32 characters; the database is SQLite; the database
password is empty, the placeholder or a well-known default (`postgres`,
`password`, `foriflow`, …); `FORIFLOW_CORS_ORIGINS`,
`FORIFLOW_JWT_EXPIRE_MINUTES` or `FORIFLOW_MAX_BODY_BYTES` is invalid. A
database password under 12 characters is a warning.

### Environment variables

| Variable | Required | Default | Notes |
|---|:---:|---|---|
| `FORIFLOW_ENV` | – | `development` (`production` in Docker) | See above. |
| `POSTGRES_USER`, `POSTGRES_DB` | ✓ (Docker) | – | |
| `POSTGRES_PASSWORD` | ✓ (Docker) | – | Unique, 12+ characters. Secret. |
| `POSTGRES_HOST`, `POSTGRES_PORT` | – | `127.0.0.1`, `5432` | Compose sets `db`. |
| `FORIFLOW_DATABASE_URL` | – | built from `POSTGRES_*` | Wins when set. Contains a secret. |
| `JWT_SECRET_KEY` | ✓ | – | 32+ random characters. Secret. Changing it signs everyone out. |
| `FORIFLOW_JWT_EXPIRE_MINUTES` | – | `480` | 15 to 720. |
| `FORIFLOW_CORS_ORIGINS` | – | see above | No `*`. |
| `FORIFLOW_ENABLE_DOCS` | – | dev on / prod off | |
| `FORIFLOW_MAX_BODY_BYTES` | – | `3145728` | At least 65,536. |
| `FORIFLOW_LOG_LEVEL` | – | `INFO` | `DEBUG` adds detail but never secrets. |
| `FORIFLOW_SCORING_ENGINE` | – | `auto` | `ml`, `surrogate`, `auto`. |
| `MANAGER_APPROVAL_LIMIT_PKR` | – | `2000000` | Read once, for the first policy. |
| `FORIFLOW_ADMIN_USERNAME`, `FORIFLOW_ADMIN_PASSWORD` | seed only | – | Used by `scripts.seed_admin`. Secret; remove from `.env` after seeding. |
| `VITE_API_BASE_URL` | – | `/api` | Build-time; leave unset for Docker. |

The model files are baked into the backend image (`backend/ml/`); there is
no model-path variable to point at another file.

## 7. Secret management

- Secrets live only in `.env` (repository root). `.env` and `.env.*` are in
  `.gitignore`; only `.env.example`, with `CHANGE_ME` placeholders, is
  committed. No secret is hard-coded; there is no default JWT secret.
- Generate the JWT secret with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`; use a
  password manager for the database and admin passwords.
- `docker-compose.yml` reads `.env` and passes it to the API container
  (`env_file`), so every variable in `.env`, including
  `FORIFLOW_ADMIN_PASSWORD`, is visible to anyone who can run
  `docker inspect` on the laptop. **Delete `FORIFLOW_ADMIN_PASSWORD` from
  `.env` once the first admin exists.**
- `/health`, `/health/ready` and the start-up log name settings, never their
  values.
- Rotation: change the value in `.env` and run `docker compose up -d`
  (`JWT_SECRET_KEY` signs everyone out; `POSTGRES_PASSWORD` must also be
  changed inside PostgreSQL with `ALTER ROLE`, see
  [docs/backup-restore.md](docs/backup-restore.md)).

## 8. Database, backup, restore and migrations

Full procedure: **[docs/backup-restore.md](docs/backup-restore.md)**.

- `backup.bat` / `scripts/backup.sh`: `pg_dump -Fc` to
  `backups/foriflow-YYYYMMDD-HHMMSS.dump`, then proves the file is a
  readable archive. Read-only for the database.
- `verify-backup.bat` / `scripts/verify-backup.sh`: restores a backup into a
  **scratch** database, compares row counts of every table, the migration
  version, the newest audit entry and the audit append-only triggers with the
  live database, then drops the scratch copy. Read-only for the live data.
- `restore.bat` / `scripts/restore.sh`: **destructive**. Takes a safety backup
  first, asks you to type `RESTORE`, stops the API and dashboard, replaces the
  database and starts them again.
- `backups/` is in `.gitignore`. Dumps contain borrower data: store them
  encrypted and off the laptop.
- Migrations run automatically when the API starts (Alembic, PostgreSQL).
  Take a backup before every upgrade (the `aa-update-*.bat` scripts do).
  Migration 0010 only adds a column and two tables; migrations 0008, 0009
  and 0010 have tested downgrade-and-upgrade round trips on PostgreSQL.

## 9. Health and readiness

| Endpoint | Auth | Answers | Use |
|---|:---:|---|---|
| `GET /health/live` | none | `200 {"status":"alive"}` while the process runs | Liveness probe. |
| `GET /health/ready` | none | `200` when the database answers, the trained model is serving (or the fallback was pinned on purpose) and the configuration is safe; otherwise `503` with each failing check named | Docker healthcheck (2.3). |
| `GET /health` | none | Version, database status, scoring engine, model version, fallback reason. Always `200`. | Dashboard status pill; kept for compatibility. |

None of them returns a secret, a connection string, a host name or a
configuration value.

## 10. Audit trail

- `audit_logs` is append-only three times over: the ORM refuses updates and
  deletes; PostgreSQL triggers reject `UPDATE`, `DELETE` and `TRUNCATE`; and no
  API route can change an entry (`/audit/logs` is `GET`, admin only). A wrong
  entry is corrected by writing another.
- Each entry has the actor (user id, username and role as they were), time
  (UTC), action, entity, before/after state where relevant, client address
  and request id.
- Security events recorded (2.3 additions in bold): sign-in, failed sign-in
  (with the count in the window), **lockout started, refused while locked,
  address rate-limited (once per window), refused for a disabled account,
  sign-out, account disabled, account enabled**, account created, approval
  refused for lack of authority, EWS override refused.
- The client address is stored for accountability. Behind nginx it is the
  `X-Real-IP` nginx sets, believed only from a private or loopback peer.
- **Limitation:** the API connects as the database owner, which could drop
  the triggers. A bank deployment should run the API as a separate role
  without `TRIGGER`/`DDL` rights on `audit_logs` and ship the trail to a
  write-once store (see §12).

## 11. Dependencies and containers

Audited for 2.3.0 with `pip-audit` (resolved `requirements.txt` and the
installed environment) and `npm audit`.

| Finding | Severity | Affects ForiFlow? | Action |
|---|---|---|---|
| `axios` ≤ 1.19.0: prototype-pollution gadgets, header injection, SSRF/proxy issues (GHSA-vh66-26gq-q6x8 and 11 related) | high | Low: the dashboard calls only its own `/api` with fixed URLs; most issues are in the Node adapters, not the browser. | **Fixed:** 1.20.0 (lockfile, `npm audit fix`, no `--force`). |
| `source-map-js` ≤ 1.2.1: DoS via crafted source maps (GHSA-68fv-2mgg-jv7q) | high | No: build-time only, our own sources. | **Fixed:** 1.2.2. |
| `pip` 24.x in the build environment (several PYSEC 2026 advisories) | medium | No: pip runs only while the image is built, from `requirements.txt`. | Not shipped as a runtime dependency; noted. |
| `passlib` 1.7.4 is unmaintained; it pins `bcrypt<4.1` and imports the `crypt` module removed in Python 3.13 | – | No known vulnerability; works on the image's Python 3.12. | Remaining: replace with direct `bcrypt` before moving to Python 3.13 (hashes stay compatible). |
| Python runtime packages (FastAPI, Starlette, SQLAlchemy, Pydantic, PyJWT, psycopg2, uvicorn) | – | `pip-audit`: no known vulnerabilities. | None. |

After the fixes `npm audit` reports 0 vulnerabilities.

Containers: the API runs as uid 10001 and nginx as its unprivileged `nginx`
user (2.3; it was root), both with every Linux capability dropped and
`no-new-privileges`. Base images are pinned (`python:3.12-slim`,
`node:20-bookworm-slim` build stage only, `nginx:1.27-alpine`,
`postgres:16.6`). All published ports are bound to 127.0.0.1. Healthchecks:
API `/health/ready`, dashboard `/`, database `pg_isready`.

## 12. Known limitations

- No independent penetration test, code audit or certification.
- No multi-factor authentication and no single sign-on.
- Tokens live in browser `localStorage` (readable by any script in the page;
  mitigated by the CSP, not eliminated).
- No branch, team or portfolio scoping: every officer reads the whole
  portfolio.
- Sign-in rate limiting per address is in process memory (single worker).
- The API's database role owns the tables and could drop the audit triggers;
  no separate least-privilege role, no external write-once audit copy.
- No encryption at rest inside ForiFlow (rely on disk encryption); backups
  are not encrypted by the scripts.
- Plain HTTP on 127.0.0.1. Putting ForiFlow on a network needs TLS in front
  (the API then sends HSTS) and a review of every item here.
- The password blocklist is short, not a breached-password corpus.
- `passlib` is unmaintained (§11).
- The stack runs on one laptop: no high availability; restores are manual.

## 13. Reporting a problem

Report a suspected vulnerability privately to the maintainers (see
`CONTRIBUTING.md`), not in a public issue. Include steps to reproduce and the
request id from any error message.
