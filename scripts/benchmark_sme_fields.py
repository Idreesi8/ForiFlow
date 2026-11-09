"""Publish aggregate research results from the verified public data cache."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from io import StringIO, TextIOWrapper
import json
from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile

import numpy as np
import pandas as pd
from sklearn import __version__ as sklearn_version
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from audit_sme_datasets import RAW, ROOT, verified_sources


def compare(train, test, variants):
    """Fit the same estimator on the same rows for every feature set."""
    results = []
    for label, columns in variants:
        model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
        model.fit(np.arcsinh(train[columns]), train['event'])
        scores = model.predict_proba(np.arcsinh(test[columns]))[:, 1]
        results.append({
            'label': label,
            'roc_auc': round(float(roc_auc_score(test['event'], scores)), 6),
            'average_precision': round(float(average_precision_score(test['event'], scores)), 6),
        })
    return results


def polish_study():
    with ZipFile(RAW / 'polish-company-bankruptcy.zip') as archive:
        text = archive.read('5year.arff').decode('utf-8')
    header, data = text.lower().split('@data', 1)
    columns = ['attr1', 'attr3', 'attr9', 'attr47', 'attr2']
    names = [line.split()[1] for line in header.splitlines() if line.startswith('@attribute ')]
    if names != [f'attr{i}' for i in range(1, 65)] + ['class']:
        raise ValueError('Unexpected UCI ARFF schema')
    rows = pd.read_csv(StringIO(data), names=names, usecols=columns + ['class'],
                       na_values='?', comment='%').rename(columns={'class': 'event'})
    if len(rows) != 5910 or rows['event'].value_counts().to_dict() != {0: 5500, 1: 410}:
        raise ValueError('Unexpected UCI one-year cohort counts')
    usable = rows.replace([np.inf, -np.inf], np.nan).dropna()
    usable = usable.loc[usable['attr47'].gt(0) & usable['attr2'].ge(0)]
    # Remove identical predictor vectors before splitting. Conflicting labels
    # cannot be resolved from the public data, so withhold the entire vector.
    groups = usable.groupby(columns, sort=False)['event']
    consistent = usable.loc[groups.transform('nunique').eq(1)]
    unique = consistent.drop_duplicates(subset=columns)
    train, test = train_test_split(unique, test_size=0.25, random_state=42, stratify=unique['event'])
    base = columns[:3]
    return {
        'source_rows': len(rows),
        'usable_rows': len(usable),
        'conflicting_rows_excluded': len(usable) - len(consistent),
        'duplicate_rows_excluded': len(consistent) - len(unique),
        'train_rows': len(train),
        'test_rows': len(test),
        'test_events': int(test['event'].sum()),
        'models': compare(train, test, [
            ('Financial ratios baseline', base),
            ('Baseline + inventory days', base + ['attr47']),
            ('Baseline + liabilities/assets', base + ['attr2']),
        ]),
    }


def sba_study():
    columns = ['LoanNr_ChkDgt', 'State', 'NAICS', 'Term', 'GrAppv', 'NoEmp',
               'MIS_Status', 'Default', 'DisbursementDate', 'ChgOffDate']
    rows = pd.read_csv(RAW / 'sba-case.csv', usecols=columns, encoding='utf-8-sig')
    status = rows['MIS_Status'].map({'P I F': 0, 'CHGOFF': 1})
    if (len(rows) != 2102 or not rows['LoanNr_ChkDgt'].is_unique
            or not rows['State'].eq('CA').all() or not rows['NAICS'].astype(str).str.startswith('53').all()
            or not status.eq(rows['Default']).all()):
        raise ValueError('Unexpected SBA teaching cohort')
    predictors = ['GrAppv', 'Term', 'NoEmp']
    valid = np.isfinite(rows[predictors]).all(axis=1)
    valid &= rows['GrAppv'].gt(0) & rows['Term'].between(1, 360) & rows['NoEmp'].ge(0)
    disbursed = pd.to_datetime(rows['DisbursementDate'], unit='D', origin='1960-01-01')
    charge_off = pd.to_datetime(rows['ChgOffDate'], unit='D', origin='1960-01-01')
    valid &= disbursed.notna()
    data = rows.loc[valid, predictors + ['Default']].rename(columns={'Default': 'event'})
    year = disbursed.loc[valid].dt.year
    train = data.loc[year.between(1989, 2005)]
    test = data.loc[year.between(2006, 2010)]
    if len(train) + len(test) != len(data):
        raise ValueError('Unexpected SBA disbursement year')
    dated_events = rows['Default'].eq(1) & charge_off.ge(disbursed)
    elapsed_months = (charge_off.dt.year - disbursed.dt.year) * 12 + charge_off.dt.month - disbursed.dt.month
    return {
        'source_rows': len(rows),
        'eligible_rows': len(data),
        'train_rows': len(train),
        'test_rows': len(test),
        'test_events': int(test['event'].sum()),
        'test_median_term_months': float(test['Term'].median()),
        'dated_charge_offs': int(dated_events.sum()),
        'terms_within_one_month_of_charge_off': int((dated_events & rows['Term'].sub(elapsed_months).abs().le(1)).sum()),
        'models': compare(train, test, [
            ('Approved amount baseline', ['GrAppv']),
            ('Baseline + loan term', ['GrAppv', 'Term']),
            ('Baseline + recorded employees', ['GrAppv', 'NoEmp']),
        ]),
    }


def retail_study():
    columns = ['invoice_no', 'quantity', 'invoice_date', 'unit_price']
    rows = pd.read_csv(RAW / 'retail-sample.csv', usecols=columns, dtype={'invoice_no': str})
    dates = pd.to_datetime(rows['invoice_date'], format='%Y-%m-%d %H:%M:%S')
    if (len(rows) != 1000 or dates.isna().any()
            or not dates.dt.normalize().eq(pd.Timestamp('2010-12-01')).all()):
        raise ValueError('Unexpected retail sample coverage')
    eligible = rows['invoice_no'].str.fullmatch('[0-9]{6}', na=False) & rows['quantity'].gt(0) & rows['unit_price'].gt(0)
    return {
        'source_rows': len(rows),
        'eligible_lines': int(eligible.sum()),
        'unique_invoices': int(rows.loc[eligible, 'invoice_no'].nunique()),
        'window_start': dates.min().isoformat(),
        'window_end': dates.max().isoformat(),
        'complete_months': 0,
    }


def ssbf_study(gzip):
    columns = ['A0_IMPLICAT', 'A10_1', 'A10_2', 'A_TOTEMP', 'XA10_1', 'XA10_2', 'S1', 'XS1']
    with subprocess.Popen([gzip, '-dc', str(RAW / 'ssbf03.dat.Z')], stdout=subprocess.PIPE) as process:
        with TextIOWrapper(process.stdout, encoding='ascii', newline='') as stream:
            data = pd.read_csv(stream, usecols=columns, low_memory=False)
        if process.wait() != 0:
            raise ValueError('Could not decompress Federal Reserve survey data')
    firms = data.loc[data['A0_IMPLICAT'].eq(1)]
    if len(data) != 21200 or len(firms) != 4240:
        raise ValueError('Unexpected survey implicate counts')
    debt = pd.to_numeric(firms['S1'], errors='coerce')
    reported_debt = debt.loc[firms['XS1'].eq(1) & np.isfinite(debt) & debt.ge(0)]
    workers = pd.to_numeric(firms['A_TOTEMP'], errors='coerce')
    total = pd.to_numeric(firms['A10_1'], errors='coerce') + pd.to_numeric(firms['A10_2'], errors='coerce')
    reported_workers = workers.loc[
        firms['XA10_1'].eq(1) & firms['XA10_2'].eq(1) & workers.eq(total) & workers.ge(0)
    ]
    return {
        'source_rows': len(data), 'firms': len(firms),
        'reported_debt_firms': len(reported_debt),
        'positive_debt_firms': int(reported_debt.gt(0).sum()),
        'median_positive_debt_usd': float(reported_debt.loc[reported_debt.gt(0)].median()),
        'reported_headcount_firms': len(reported_workers),
        'median_reported_headcount': float(reported_workers.median()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gzip', default=shutil.which('gzip'), help='gzip executable with .Z support')
    args = parser.parse_args()
    if not args.gzip:
        parser.error('Pass the path to gzip with --gzip')
    sources = verified_sources()
    relevant = ('polish', 'sba_loans', 'retail_orders', 'ssbf', 'ssbf_layout')
    report = {
        'schema_version': 1,
        'completed_at': datetime.now(timezone.utc).isoformat(),
        'software': {'numpy': np.__version__, 'pandas': pd.__version__, 'scikit_learn': sklearn_version},
        'sources': {key: {field: sources[key][field] for field in ('page', 'url', 'sha256', 'license')}
                    for key in relevant},
        'polish': polish_study(),
        'sba_loans': sba_study(),
        'retail_orders': retail_study(),
        'ssbf': ssbf_study(args.gzip),
    }
    output = ROOT / 'backend/ml/sme_dataset_benchmarks.json'
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
