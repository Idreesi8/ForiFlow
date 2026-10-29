"""Dates must be explicit or unambiguous; repeated records stay auditable."""
import hashlib
from datetime import date

import pytest

from services.cashflow_import import prepare_source
from services.cashflow_intelligence import analyse_csv
from services.statement_service import StatementError, parse_statement


def iso():
    return 'date,type,amount\n'+'\n'.join(f'2026-{m:02d}-02,CR,100000\n2026-{m:02d}-27,DR,50000' for m in range(1,4))+'\n'


def numeric(order):
    return 'date,type,amount\n'+'\n'.join((f'02/{m:02d}/2026,CR,100000\n27/{m:02d}/2026,DR,50000' if order=='day_first' else f'{m:02d}/02/2026,CR,100000\n{m:02d}/27/2026,DR,50000') for m in range(1,4))+'\n'


def ambiguous():
    return 'date,type,amount\n'+'\n'.join(f'{value},CR,100000' for value in ['02/01/2026','02/02/2026','02/03/2026','04/04/2026','10/05/2026'])


def test_iso_keeps_exact_financial_results_and_original_source_fingerprint():
    source=iso()
    summary,quality=prepare_source(source)
    canonical=parse_statement(source)
    assert summary.months == canonical.months
    assert summary.source_sha256 == hashlib.sha256(source.encode()).hexdigest()
    assert quality.date_order_resolved == 'iso_or_named'
    assert quality.normalised_date_rows == 0 and quality.source_rows == 6
    assert quality.parsed_source_sha256 == canonical.source_sha256


@pytest.mark.parametrize('order',['day_first','month_first'])
def test_auto_uses_a_valid_unambiguous_numeric_clue(order):
    summary,quality=prepare_source(numeric(order))
    assert quality.date_order_resolved == order
    assert quality.ambiguous_numeric_rows == 2
    assert summary.months == parse_statement(iso()).months
    assert quality.normalised_date_rows == 6


def test_automatic_mode_never_guesses_all_ambiguous_dates():
    with pytest.raises(StatementError,match='Ambiguous numeric dates.*Select Day'):
        prepare_source(ambiguous())


def test_explicit_date_conventions_produce_different_auditable_calendar_months():
    day,dq=prepare_source(ambiguous(),'day_first')
    month,mq=prepare_source(ambiguous(),'month_first')
    assert day.months[0].month == '2026-01' and day.months[-1].month == '2026-04'
    assert month.months[0].month == '2026-02' and month.months[-1].month == '2026-09'
    assert dq.ambiguous_numeric_rows == mq.ambiguous_numeric_rows == 3
    assert day.source_sha256 == month.source_sha256
    assert dq.parsed_source_sha256 != mq.parsed_source_sha256


def test_auto_rejects_mixed_known_numeric_conventions():
    source=numeric('day_first')+'01/27/2026,CR,1000\n'
    with pytest.raises(StatementError,match='mixes day-first and month-first'):
        prepare_source(source)


def test_explicit_order_never_falls_back_to_the_opposite_order_for_invalid_rows():
    source=iso()+'01/27/2026,CR,999999\n'
    summary,quality=prepare_source(source,'day_first')
    assert summary.unreadable_transactions == 1
    assert summary.months == parse_statement(iso()).months
    assert quality.date_order_requested == 'day_first'
    result=analyse_csv(source,'day_first',today=date(2026,10,28))
    assert result.forecast.status == 'quality_blocked'


@pytest.mark.parametrize('order',['auto','day_first','month_first'])
def test_iso_and_named_months_are_not_reinterpreted_by_numeric_setting(order):
    source=iso().replace('2026-01-02','02-Jan-2026').replace('2026-02-27','27 Feb 2026')
    summary,_=prepare_source(source,order)
    assert summary.months == parse_statement(iso()).months


def test_identical_day_and_month_need_no_guess():
    source='date,type,amount\n01/01/2026,CR,100\n02/02/2026,CR,200\n03/03/2026,CR,300\n04/04/2026,CR,400\n'
    summary,quality=prepare_source(source)
    assert quality.date_order_resolved == 'identical_day_month'
    assert quality.ambiguous_numeric_rows == 0 and summary.full_months == 3


def test_repeated_rows_are_counted_and_retained_without_fraud_or_dedup_claim():
    source=iso()+'2026-01-02,CR,100000\n'
    summary,quality=prepare_source(source)
    assert summary.months[0].inflow == 200000 and summary.transactions == 7
    assert quality.repeated_row_candidates == 1
    assert quality.repeated_row_examples[0].model_dump() == {'first_line':2,'repeated_line':8}
    assert any('No rows were removed' in warning for warning in summary.warnings)


def test_same_amount_and_date_with_different_references_are_not_identical_records():
    source=iso().replace('date,type,amount','date,type,amount,reference')
    lines=source.splitlines(); source='\n'.join([lines[0]]+[line+f',ref-{i}' for i,line in enumerate(lines[1:])])
    source+='\n2026-01-02,CR,100000,different-reference\n'
    _,quality=prepare_source(source)
    assert quality.repeated_row_candidates == 0


def test_repeat_examples_are_bounded_but_total_count_is_complete():
    source=iso()+'2026-01-02,CR,100000\n'*25
    summary,quality=prepare_source(source)
    assert quality.repeated_row_candidates == 25 and len(quality.repeated_row_examples) == 10
    assert summary.transactions == 31


@pytest.mark.parametrize('source',[
    'date,type,amount,AMOUNT\n2026-01-02,CR,100,100',
    'date,transaction date,amount\n2026-01-02,2026-01-03,100',
    'date,type,amount\n2026-01-02,CR,100,extra',
    'date,type,amount\n2026-01-02,CR',
    'date,,amount\n2026-01-02,CR,100',
    'date,type,amount\n2026-01-02,CR,"100',
])
def test_structural_ambiguity_is_rejected_without_exposing_row_contents(source):
    with pytest.raises(StatementError): prepare_source(source)


def test_original_and_normalised_hashes_identify_distinct_exact_sources():
    source=numeric('day_first')
    summary,quality=prepare_source(source)
    assert summary.source_sha256 == hashlib.sha256(source.encode()).hexdigest()
    assert quality.parsed_source_sha256 == hashlib.sha256(iso().encode()).hexdigest()
    assert summary.source_sha256 != quality.parsed_source_sha256


def test_invalid_numeric_dates_are_not_a_valid_convention_clue_or_normalised_date():
    summary,quality=prepare_source(iso()+'31/31/2026,CR,500\n')
    assert summary.unreadable_transactions == 1
    assert quality.date_order_resolved == 'iso_or_named'
    assert quality.normalised_date_rows == 0


def test_line_endings_change_raw_identity_but_not_normalised_meaning():
    source=iso()
    a,aq=prepare_source(source)
    b,bq=prepare_source(source.replace('\n','\r\n'))
    assert a.source_sha256 != b.source_sha256
    assert aq.parsed_source_sha256 == bq.parsed_source_sha256 and a.months == b.months


def test_timestamp_is_a_source_calendar_date_without_timezone_conversion():
    source=iso().replace('2026-01-02','2026-01-02T23:30:00-05:00')
    summary,quality=prepare_source(source)
    assert summary.months == parse_statement(iso()).months
    assert quality.normalised_date_rows == 1


def test_quoted_multiline_records_use_physical_end_line_references():
    lines=iso().splitlines()
    source=lines[0]+',memo\n'+lines[1]+',"A\nB"\n'+'\n'.join(line+',x' for line in lines[2:])+'\n'+lines[1]+',"A\nB"\n'
    _,quality=prepare_source(source)
    assert quality.repeated_row_examples[0].model_dump() == {'first_line':3,'repeated_line':10}


def test_bom_and_quoted_fields_preserve_parser_parity_and_raw_identity():
    source='\ufeff'+iso().replace('date,type,amount','date,type,amount,description')
    source='\n'.join([source.splitlines()[0]]+[line+',"quoted, details"' for line in source.splitlines()[1:]])+'\n'
    summary,_=prepare_source(source)
    assert summary.months == parse_statement(iso()).months
    assert summary.source_sha256 == hashlib.sha256(source.encode()).hexdigest()


def test_endpoint_rejects_guess_and_returns_selected_mode_and_both_fingerprints(client):
    auto=client.post('/model/cashflow-intelligence',json={'csv':ambiguous()})
    assert auto.status_code == 422 and 'Ambiguous' in auto.json()['detail']
    chosen=client.post('/model/cashflow-intelligence',json={'csv':ambiguous(),'date_order':'day_first'})
    assert chosen.status_code == 200,chosen.text
    body=chosen.json()
    assert body['method_version'] == 'cashflow-local-v2'
    assert body['source_quality']['date_order_requested'] == 'day_first'
    assert body['source_sha256'] == hashlib.sha256(ambiguous().encode()).hexdigest()
    assert chosen.headers['cache-control'] == 'no-store'


def test_unsupported_modes_and_non_string_csv_are_rejected(client):
    for payload in [{'csv':iso(),'date_order':'guess'}, {'csv':iso(),'date_order':None}, {'csv':True}]:
        assert client.post('/model/cashflow-intelligence',json=payload).status_code == 422
