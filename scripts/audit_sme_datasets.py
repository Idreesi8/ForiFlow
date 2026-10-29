"""Inspect downloaded data only; never import or run publisher scripts/notebooks."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / '.local/datasets/sme-field-research'
OUTPUT = ROOT / 'backend/ml/sme_field_research.json'


def verified_sources() -> dict:
    manifest = json.loads((RAW / 'manifest.json').read_text())
    for source in manifest.values():
        assert hashlib.sha256((RAW / source['file']).read_bytes()).hexdigest() == source['sha256'], source['file']
    return manifest


def numeric_profile(rows: list[dict], column: str) -> dict:
    values = []
    for row in rows:
        try:
            number = float(row[column])
            if math.isfinite(number):
                values.append(number)
        except (ValueError, TypeError, KeyError):
            pass
    return {'finite': len(values), 'missing_or_nonfinite': len(rows) - len(values),
            'min': min(values) if values else None, 'max': max(values) if values else None}


def bangladesh_profile() -> dict:
    with zipfile.ZipFile(RAW / 'bangladesh-sme-v2.zip') as archive:
        matches = [name for name in archive.namelist() if name.endswith('/data/bangladesh_sme_1200_records.csv')]
        assert len(matches) == 1
        data = archive.read(matches[0])
    rows = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    assert rows and all(row['target_missed_payment'] in ('0', '1') for row in rows)
    alias = all((row['missed_payment_last_12m'] == 'Yes') == (row['target_missed_payment'] == '1') for row in rows)
    return {'rows_downloaded': len(rows), 'columns': list(rows[0]), 'csv_sha256': hashlib.sha256(data).hexdigest(),
            'target_counts': dict(Counter(row['target_missed_payment'] for row in rows)),
            'provided_split_counts': dict(Counter(row['split'] for row in rows)),
            'target_alias_identical': alias,
            'numeric_profiles': {column: numeric_profile(rows, column) for column in
                ['employees_count', 'preferred_tenure_months', 'business_age_years', 'cashflow_stability']},
            'existing_loans_levels': sorted({row['existing_loans'] for row in rows}),
            'missing_exact_columns': ['existing_debt_pkr', 'inventory_turnover', 'order_consistency'],
            'use': 'Research only: retrospective missed payment, not verified prospective SME default.',
            'limitations': ['Missed-payment text is an exact target alias and must be excluded from predictors.',
                           'Payment history and outcome timing require clarification before prospective prediction.',
                           'Existing loans is Yes/No, not an outstanding balance.',
                           'Cash-flow stability is a 1–5 rating, not the intake 0–100 order measure.',
                           'Employees inclusion of owners is not established; BDT amounts are not PKR.']}


def polish_profile() -> dict:
    cohorts = []
    with zipfile.ZipFile(RAW / 'polish-company-bankruptcy.zip') as archive:
        for year in range(1, 6):
            name = f'{year}year.arff'
            text = archive.read(name).decode('utf-8')
            header, data = text.lower().split('@data', 1)
            rows = [row for row in csv.reader(io.StringIO(data)) if row and not row[0].startswith('%')]
            assert all(len(row) == 65 and row[-1].strip() in ('0', '1') for row in rows)
            cohorts.append({'file': name, 'rows': len(rows), 'bankruptcy_horizon_years': 6 - year,
                            'bankrupt': sum(row[-1].strip() == '1' for row in rows),
                            'missing_sales_inventory_ratio': sum(row[59].strip() == '?' for row in rows)})
    return {'cohorts': cohorts, 'microdata_downloaded': True,
            'candidate_columns': {'Attr60': 'Sales / inventory', 'Attr47': 'Inventory × 365 / cost of products sold',
                                  'Attr2': 'Total liabilities / total assets'},
            'use': 'Financial-ratio bankruptcy research; no direct mapping to all intake fields.',
            'limitations': ['The five files have different outcome horizons and may contain recurring companies; do not pool them as independent firms.',
                           'Sales/inventory is not automatically COGS/average inventory.',
                           'A liabilities/assets ratio cannot supply a PKR debt balance.',
                           'Corporate bankruptcy is not the same outcome as a facility default.']}


def sba_dictionary_profile() -> dict:
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    sheets = []
    with zipfile.ZipFile(RAW / 'sba-foia-dictionary.xlsx') as archive:
        strings = [''.join(item.itertext()) for item in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('s:si', ns)]
        for sheet in ['xl/worksheets/sheet1.xml', 'xl/worksheets/sheet2.xml']:
            fields = []
            for row in ET.fromstring(archive.read(sheet)).findall('.//s:row', ns):
                cells = []
                for cell in row.findall('s:c', ns):
                    value = cell.find('s:v', ns)
                    raw = value.text if value is not None else ''
                    cells.append(strings[int(raw)] if cell.get('t') == 's' and raw else raw)
                if cells:
                    fields.append(cells[0])
            sheets.append({'sheet': sheet, 'fields': fields})
    return {'dictionary_downloaded': True, 'loan_microdata_downloaded': False, 'sheets': sheets,
            'use': 'Candidate for term/outcome research after record acquisition and cohort design.',
            'limitations': ['JobsSupported combines jobs created and retained; it is not current employee headcount.',
                           'The dictionary does not contain intake inventory turnover, order consistency or total existing debt.',
                           'Current loan status and charge-off require time/censoring design; EXEMPT cannot be labelled non-default.']}


def pakistan_profile() -> dict:
    metadata = json.loads((RAW / 'pakistan-wbes-2022-metadata.json').read_text())
    variables = metadata['variables']
    return {'reference': metadata['study_desc']['title_statement']['idno'],
            'metadata_downloaded': True, 'microdata_downloaded': False,
            'catalogue_cases': metadata['data_files'][0]['case_count'], 'catalogue_variables': len(variables),
            'use': 'Pakistan-specific business context; no prospective loan-default target established.',
            'limitations': ['Only metadata was acquired; firm-level microdata is distributed through Enterprise Surveys.',
                           'Registered firms with five or more employees; not a representative informal/microbusiness credit sample.',
                           'Survey weights and exact worker definitions are needed for peer benchmarks.',
                           'Sales, employment and credit access are not loan repayment/default outcomes.']}


def main() -> None:
    sources = verified_sources()
    profiles = {'bangladesh': bangladesh_profile(), 'polish': polish_profile(),
                'sba_dictionary': sba_dictionary_profile(), 'pakistan_metadata': pakistan_profile()}
    field_coverage = [
        {'field': 'tenure_months', 'label': 'Tenure', 'research_status': 'candidate',
         'sources': ['bangladesh', 'sba_dictionary'], 'gap': 'Preferred versus contracted term, outcome timing and cohort validation are unresolved.'},
        {'field': 'existing_debt_pkr', 'label': 'Existing debt', 'research_status': 'missing_exact_measure',
         'sources': ['bangladesh', 'polish'], 'gap': 'Loan presence and liabilities ratios do not provide an outstanding PKR debt balance or repayment schedule.'},
        {'field': 'inventory_turnover', 'label': 'Inventory turnover', 'research_status': 'definition_mismatch',
         'sources': ['polish'], 'gap': 'Financial-statement inventory ratios need a documented numerator, inventory period and matched default outcome.'},
        {'field': 'order_consistency', 'label': 'Order consistency', 'research_status': 'missing_order_history',
         'sources': ['bangladesh'], 'gap': 'A 1–5 cash-flow rating and a receipts proxy cannot replace monthly order histories and a defined 0–100 measure.'},
        {'field': 'num_employees', 'label': 'Employees', 'research_status': 'candidate',
         'sources': ['bangladesh', 'pakistan_metadata', 'sba_dictionary'], 'gap': 'Owner-inclusive headcount, target timing and population alignment require verification; jobs supported is a different measure.'},
    ]
    report = {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
              'training_ready': False, 'serving_model_changed': False,
              'gate': 'No source establishes all five exact intake measures paired with a time-bounded prospective Pakistani SME default outcome.',
              'sources': [{**sources[name], 'id': name, **profiles[name]} for name in sources],
              'field_coverage': field_coverage,
              'next_data': ['Owner-inclusive headcount and consistently defined inventory measures at application time.',
                            'Monthly order/receipt history and actual existing-debt instalments.',
                            'Loan origination dates, borrower grouping, repayments and a fixed future default window.',
                            'Documented consent/licence, time-based/borrower-separated evaluation and calibration.']}
    OUTPUT.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(OUTPUT), 'sources': len(sources), 'training_ready': False,
                      'bangladesh_rows': profiles['bangladesh']['rows_downloaded'],
                      'polish_cohort_rows': [row['rows'] for row in profiles['polish']['cohorts']]}))


if __name__ == '__main__':
    main()
