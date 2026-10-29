"""Turn a wallet or bank statement into the turnover figures the model reads.

Facility size against turnover carries more than half of the score, and until
now an officer typed the turnover. This module computes it from the statement
itself: a CSV export of the applicant's merchant wallet (JazzCash, Easypaisa)
or bank account, with one row per transaction.

It is deliberately forgiving about column names and strict about content. It
does not produce a repayment-history score: the model reads that field as a
bureau record (default on file or not), which a statement cannot show.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

MAX_STATEMENT_CHARS = 2_000_000
STATEMENT_PARSER_VERSION = 'statement-v2'
MIN_FULL_MONTHS = 3
# A boundary month is kept only if the statement covers it from at least this
# early / to at least this late; otherwise it would understate the month.
FULL_MONTH_STARTS_BY_DAY = 5
FULL_MONTH_ENDS_FROM_DAY = 25
# One inflow above this share of all inflows is flagged: a loan disbursement or
# a capital injection is not turnover.
LARGE_INFLOW_SHARE = 0.25

DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d-%b-%Y",
    "%d %b %Y",
    "%d/%m/%y",
    "%Y/%m/%d",
    "%m/%d/%Y",
)

DATE_COLUMNS = ("date", "transaction date", "txn date", "datetime", "date time", "time")
AMOUNT_COLUMNS = ("amount", "amt", "transaction amount", "txn amount")
CREDIT_COLUMNS = ("credit", "cr", "money in", "inflow", "deposit", "received", "paid in")
DEBIT_COLUMNS = ("debit", "dr", "money out", "outflow", "withdrawal", "sent", "paid out")
DIRECTION_COLUMNS = ("type", "direction", "dr/cr", "cr/dr", "transaction type", "txn type")
STATUS_COLUMNS = ("status", "transaction status", "txn status")

INFLOW_WORDS = ("cr", "credit", "in", "received", "deposit", "inflow", "incoming")
OUTFLOW_WORDS = ("dr", "debit", "out", "sent", "withdrawal", "outflow", "outgoing")
FAILED_WORDS = ("fail", "revers", "declin", "cancel", "reject", "pending")


class StatementError(ValueError):
    """The statement could not be read; the message says what to fix."""


@dataclass(frozen=True, slots=True)
class MonthTotals:
    """One calendar month of the statement."""

    month: str
    inflow: float
    outflow: float
    transactions: int


@dataclass(frozen=True, slots=True)
class StatementSummary:
    """What the statement says about turnover, and what to check by hand."""

    period_start: str
    period_end: str
    transactions: int
    failed_transactions: int
    full_months: int
    months: list[MonthTotals]
    monthly_inflow_median: float
    monthly_net_median: float
    inflow_variation: float
    inflow_to_outflow: float | None
    suggested_monthly_digital_payments: float
    suggested_cash_flow_proxy: float
    suggested_order_consistency: float
    warnings: list[str] = field(default_factory=list)
    unreadable_transactions: int = 0
    months_without_transactions: list[str] = field(default_factory=list)
    source_sha256: str = ''
    parser_version: str = STATEMENT_PARSER_VERSION

    def as_dict(self) -> dict:
        """Plain dict for JSON storage and API responses."""
        return asdict(self)


def _clean(name: str) -> str:
    return re.sub(r"[\s_]+", " ", name.strip().lower())


def _find(header: list[str], names: tuple[str, ...]) -> str | None:
    cleaned = {_clean(column): column for column in header}
    return next((cleaned[name] for name in names if name in cleaned), None)


def _amount(text: str) -> float | None:
    text = re.sub(r"(?i)pkr|rs\.?|,|\s", "", text or "")
    if text in ("", "-"):
        return None
    negative = text.startswith("(") and text.endswith(")")
    try:
        value = float(text.strip("()"))
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return -value if negative else value


def _date(text: str) -> date | None:
    text = (text or "").strip()
    for candidate in (text, text.split(" ")[0], text.split("T")[0]):
        for pattern in DATE_FORMATS:
            try:
                return datetime.strptime(candidate, pattern).date()
            except ValueError:
                continue
    return None


def parse_statement(csv_text: str) -> StatementSummary:
    """Read a statement CSV and summarise turnover by full calendar month."""
    if len(csv_text) > MAX_STATEMENT_CHARS:
        raise StatementError("The statement is larger than 2 MB. Export a shorter period.")
    try:
        return _parse_statement(csv_text)
    except csv.Error as exc:
        raise StatementError(
            "The CSV could not be read. Check its format and export it again."
        ) from exc


def _parse_statement(csv_text: str) -> StatementSummary:
    """Parse CSV rows; the public entry point translates CSV format errors."""
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")), strict=True)
    header = reader.fieldnames or []

    date_column = _find(header, DATE_COLUMNS)
    amount_column = _find(header, AMOUNT_COLUMNS)
    credit_column = _find(header, CREDIT_COLUMNS)
    debit_column = _find(header, DEBIT_COLUMNS)
    direction_column = _find(header, DIRECTION_COLUMNS)
    status_column = _find(header, STATUS_COLUMNS)

    if date_column is None:
        raise StatementError("No date column found. Expected a column named 'date'.")
    if amount_column is None and (credit_column is None or debit_column is None):
        raise StatementError(
            "No amount found. Expected an 'amount' column, or 'credit' and 'debit' columns."
        )

    rows: list[tuple[date, float]] = []
    failed = unreadable = 0
    for row in reader:
        when = _date(row.get(date_column, ""))
        if when is None:
            unreadable += 1
            continue
        if status_column and any(
            word in (row.get(status_column) or "").lower() for word in FAILED_WORDS
        ):
            failed += 1
            continue

        if amount_column is not None:
            value = _amount(row.get(amount_column, ""))
            if value is None:
                unreadable += 1
                continue
            if direction_column is not None:
                direction = _clean(row.get(direction_column) or "")
                words = direction.split(" ")
                if any(word in INFLOW_WORDS for word in words):
                    value = abs(value)
                elif any(word in OUTFLOW_WORDS for word in words):
                    value = -abs(value)
                else:
                    unreadable += 1
                    continue
        else:
            credit_text = (row.get(credit_column) or "").strip()
            debit_text = (row.get(debit_column) or "").strip()
            credit = 0.0 if credit_text in ("", "-") else _amount(credit_text)
            debit = 0.0 if debit_text in ("", "-") else _amount(debit_text)
            if credit is None or debit is None:
                unreadable += 1
                continue
            value = abs(credit) - abs(debit)
        if value != 0:
            rows.append((when, value))

    if not rows:
        raise StatementError("No readable transactions were found in the statement.")
    rows.sort()
    start, end = rows[0][0], rows[-1][0]

    inflow: dict[str, float] = defaultdict(float)
    outflow: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    for when, value in rows:
        key = f"{when.year:04d}-{when.month:02d}"
        count[key] += 1
        if value > 0:
            inflow[key] += value
        else:
            outflow[key] += -value

    # Every calendar month inside the observed period belongs in the median.
    # Omitting a quiet month would overstate turnover and payment consistency.
    first_month = start.year * 12 + start.month - 1
    last_month = end.year * 12 + end.month - 1
    keys = [
        f"{index // 12:04d}-{index % 12 + 1:02d}"
        for index in range(first_month, last_month + 1)
    ]
    if keys and start.day > FULL_MONTH_STARTS_BY_DAY:
        keys = keys[1:]
    if keys and end.day < FULL_MONTH_ENDS_FROM_DAY:
        keys = keys[:-1]
    if len(keys) < MIN_FULL_MONTHS:
        raise StatementError(
            f"The statement covers {len(keys)} full month(s) "
            f"({start:%d %b %Y} to {end:%d %b %Y}). At least {MIN_FULL_MONTHS} are needed."
        )

    months = [
        MonthTotals(key, round(inflow[key], 2), round(outflow[key], 2), count[key])
        for key in keys
    ]
    inflows = [month.inflow for month in months]
    nets = [month.inflow - month.outflow for month in months]
    total_in, total_out = sum(inflows), sum(month.outflow for month in months)
    if not all(math.isfinite(value) for value in (total_in, total_out)):
        raise StatementError("The statement totals are too large. Check the transaction amounts.")
    if total_in <= 0:
        raise StatementError("The statement shows no money coming in.")

    mean_inflow = statistics.fmean(inflows)
    variation = statistics.pstdev(inflows) / mean_inflow if mean_inflow > 0 else 0.0
    median_inflow = statistics.median(inflows)
    median_net = statistics.median(nets)
    inflow_to_outflow = total_in / total_out if total_out > 0 else None
    if inflow_to_outflow is not None and not math.isfinite(inflow_to_outflow):
        raise StatementError("The statement ratio is too large. Check the transaction amounts.")

    warnings: list[str] = []
    quiet_months = [month.month for month in months if month.transactions == 0]
    if quiet_months:
        warnings.append(
            f"{len(quiet_months)} month(s) have no readable transactions. "
            'Confirm the export is complete; zero receipts are included for those months.'
        )
    full_month_keys = set(keys)
    in_window = [
        value for when, value in rows if f"{when.year:04d}-{when.month:02d}" in full_month_keys
    ]
    largest = max((value for value in in_window if value > 0), default=0.0)
    if largest / total_in > LARGE_INFLOW_SHARE:
        warnings.append(
            f"One inflow of PKR {largest:,.0f} is {largest / total_in:.0%} of all money in. "
            "Check that it is sales and not a loan or a transfer from the owner."
        )
    losing = sum(1 for net in nets if net < 0)
    if losing:
        warnings.append(f"More went out than came in during {losing} of {len(months)} months.")
    if variation > 0.5:
        warnings.append(
            "Monthly inflows vary widely (the spread is "
            f"{variation:.0%} of the average). The median is used, not the best month."
        )
    if unreadable:
        warnings.append(f"{unreadable} row(s) could not be read and were left out.")
    if failed:
        warnings.append(f"{failed} failed, reversed or pending transaction(s) were left out.")

    return StatementSummary(
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        transactions=sum(month.transactions for month in months),
        failed_transactions=failed,
        full_months=len(months),
        months=months,
        monthly_inflow_median=round(median_inflow, 2),
        monthly_net_median=round(median_net, 2),
        inflow_variation=round(variation, 4),
        inflow_to_outflow=round(inflow_to_outflow, 4) if inflow_to_outflow is not None else None,
        suggested_monthly_digital_payments=float(round(median_inflow)),
        suggested_cash_flow_proxy=float(round(max(median_net, 0.0))),
        suggested_order_consistency=float(round(100.0 * (1.0 - min(variation, 1.0)))),
        warnings=warnings,
        unreadable_transactions=unreadable,
        months_without_transactions=quiet_months,
        source_sha256=hashlib.sha256(csv_text.encode('utf-8')).hexdigest(),
    )
