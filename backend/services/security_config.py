"""Start-up configuration checks (2.3).

``configuration_report()`` lists what is wrong with the environment by NAME
only. It never returns, logs or prints a secret's value, so its output is safe
for logs, the readiness endpoint and the update scripts.

In production every *problem* stops the API from starting; *warnings* are
logged. In development problems are logged as warnings so a laptop run still
starts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.engine import make_url

import config
from services.auth_service import jwt_secret_problem

# Passwords a scanner tries first against PostgreSQL.
WEAK_DATABASE_PASSWORDS = frozenset(
    {
        "", "postgres", "password", "admin", "root", "secret", "foriflow", "changeme",
        "change_me", "123456", "12345678", "1234567890", "qwerty", "letmein", "test",
    }
)
MIN_DATABASE_PASSWORD_LENGTH = 12


@dataclass
class ConfigurationReport:
    environment: str
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def configuration_report(database_url: str | None = None) -> ConfigurationReport:
    """Check the environment. Names settings; never echoes their values."""
    try:
        environment = config.app_env()
    except RuntimeError as exc:
        return ConfigurationReport(environment="invalid", problems=[str(exc)])
    report = ConfigurationReport(environment=environment)
    production = environment == "production"

    secret_problem = jwt_secret_problem(config.jwt_secret_key())
    if secret_problem:
        report.problems.append(secret_problem)

    url_text = database_url if database_url is not None else config.database_url()
    if config.is_sqlite_url(url_text):
        if production:
            report.problems.append(
                "Production needs PostgreSQL: set POSTGRES_* (or FORIFLOW_DATABASE_URL); "
                "SQLite is for development and tests only."
            )
    else:
        try:
            password = make_url(url_text).password or ""
        except Exception:  # noqa: BLE001 - an unparsable URL is reported, not raised
            report.problems.append("The database URL cannot be parsed.")
            password = None
        if password is not None:
            if password.startswith("CHANGE_ME") or password.lower() in WEAK_DATABASE_PASSWORDS:
                report.problems.append(
                    "POSTGRES_PASSWORD is empty, the .env.example placeholder or a well-known "
                    "default. Set a unique password."
                )
            elif len(password) < MIN_DATABASE_PASSWORD_LENGTH:
                report.warnings.append(
                    f"POSTGRES_PASSWORD is shorter than {MIN_DATABASE_PASSWORD_LENGTH} "
                    "characters. Use a longer one at the next rotation."
                )

    for name, check in (
        ("FORIFLOW_CORS_ORIGINS", config.cors_origins),
        ("FORIFLOW_JWT_EXPIRE_MINUTES", config.jwt_expire_minutes),
        ("FORIFLOW_MAX_BODY_BYTES", config.max_body_bytes),
    ):
        try:
            check()
        except RuntimeError as exc:
            report.problems.append(f"{name}: {exc}")

    if production and config.docs_requested():
        report.warnings.append(
            "FORIFLOW_ENABLE_DOCS=true is ignored in production: /docs, /redoc and "
            "/openapi.json stay disabled. Set it to false in .env."
        )

    if not production:
        # Development still starts; the problems become loud warnings.
        report.warnings = [*report.problems, *report.warnings]
        report.problems = []
    return report
