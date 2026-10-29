"""Statement turnover must include quiet months and reject unusable amounts."""

from __future__ import annotations

import json

import pytest

from services.statement_service import StatementError, parse_statement


def test_quiet_months_are_included_in_turnover_and_consistency() -> None:
    statement = "date,type,amount\n" + "\n".join(
        f"2026-{month}-02,CR,100000\n2026-{month}-27,DR,60000"
        for month in ("01", "04", "06")
    )

    summary = parse_statement(statement)

    assert summary.full_months == 6
    assert [month.month for month in summary.months] == [
        f"2026-{month:02d}" for month in range(1, 7)
    ]
    assert summary.months[1].inflow == summary.months[1].outflow == 0
    assert summary.months[1].transactions == 0
    assert summary.transactions == 6
    assert summary.suggested_monthly_digital_payments == 50_000
    assert summary.suggested_cash_flow_proxy == 20_000
    assert summary.inflow_variation == 1
    assert summary.suggested_order_consistency == 0


def test_partial_boundary_months_exclude_only_the_boundaries() -> None:
    summary = parse_statement(
        "date,type,amount\n"
        "2025-12-20,CR,100000\n"
        "2026-02-10,CR,90000\n"
        "2026-04-03,DR,1000\n"
    )

    assert [month.month for month in summary.months] == [
        "2026-01", "2026-02", "2026-03"
    ]
    assert summary.transactions == 1
    assert summary.suggested_monthly_digital_payments == 0


@pytest.mark.parametrize("amount", ["NaN", "inf", "-inf", "1e309"])
@pytest.mark.parametrize("header,row", [
    ("date,type,amount", "{date},CR,{amount}"),
    ("date,credit,debit", "{date},{amount},"),
    ("date,credit,debit", "{date},,{amount}"),
])
def test_nonfinite_amounts_are_unreadable(amount: str, header: str, row: str) -> None:
    statement = header + "\n" + "\n".join(
        row.format(date=f"2026-{month}-02", amount=amount)
        for month in ("01", "02", "03")
    )

    with pytest.raises(StatementError, match="No readable transactions"):
        parse_statement(statement)


@pytest.mark.parametrize("amount", ["NaN", "inf", "not-a-number"])
def test_invalid_debit_does_not_turn_a_row_into_valid_inflow(amount: str) -> None:
    statement = "date,credit,debit\n" + "\n".join(
        f"2026-{month}-02,100000,\n2026-{month}-27,,60000"
        for month in ("01", "02", "03")
    )
    statement += f"\n2026-02-10,500000,{amount}"

    summary = parse_statement(statement)

    assert summary.transactions == 6
    assert summary.inflow_variation == 0
    assert any("1 row(s) could not be read" in warning for warning in summary.warnings)
    json.dumps(summary.as_dict(), allow_nan=False)


def test_overflowing_monthly_total_is_refused() -> None:
    statement = "date,type,amount\n" + "\n".join(
        f"2026-{month}-02,CR,1e308\n2026-{month}-27,CR,1e308"
        for month in ("01", "02", "03")
    )

    with pytest.raises(StatementError, match="too large"):
        parse_statement(statement)


def test_unreadable_csv_field_is_a_statement_error() -> None:
    with pytest.raises(StatementError, match="CSV"):
        parse_statement("date,type,amount\n2026-01-02,CR," + "1" * 200_000)


def test_unclosed_csv_quote_is_a_statement_error() -> None:
    with pytest.raises(StatementError, match="CSV"):
        parse_statement('date,type,amount\n2026-01-02,CR,"100000')
