"""Link an approved lender export and evaluate candidates offline."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import re
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator

from business_time import BUSINESS_TIMEZONE, business_date, utc_now


SPLITS = ('train', 'calibration', 'test')
BASE = ('requested_amount_pkr', 'annual_turnover_pkr', 'payment_history_score', 'years_in_operation')
ADDITIONAL = ('tenure_months', 'existing_debt_pkr', 'inventory_turnover', 'order_consistency', 'num_employees')


def calendar_date(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return date.fromisoformat(value)
    raise ValueError('Use an ISO calendar date.')


def timestamp(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', value):
        return datetime.fromisoformat(value)
    raise ValueError('Use an ISO timestamp with a time zone offset.')


CalendarDate = Annotated[date, BeforeValidator(calendar_date)]
Timestamp = Annotated[AwareDatetime, BeforeValidator(timestamp)]


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, str_strip_whitespace=True)


class Window(Record):
    first: CalendarDate
    last: CalendarDate


class Protocol(Record):
    schema_version: Literal[1]
    country: Literal['PK']
    product_code: str = Field(min_length=1, max_length=100)
    target_definition_ref: str = Field(min_length=1, max_length=200)
    training_authority_ref: str = Field(min_length=1, max_length=200)
    snapshot_at: Timestamp
    horizon_days: int = Field(strict=True, ge=1, le=1095)
    event_dpd: int = Field(strict=True, ge=1, le=3650)
    minimum_per_class: int = Field(strict=True, ge=2)
    train: Window
    calibration: Window
    test: Window

    @model_validator(mode='after')
    def chronological(self):
        if not self.train.first <= self.train.last < self.calibration.first <= self.calibration.last < self.test.first <= self.test.last:
            raise ValueError('Cohort windows must be ordered and disjoint.')
        if self.snapshot_at > utc_now():
            raise ValueError('The snapshot cannot be in the future.')
        if self.event_dpd > self.horizon_days:
            raise ValueError('The DPD threshold cannot exceed the horizon for newly disbursed loans.')
        return self

    def partition(self, disbursed_on: date) -> str | None:
        return next((name for name in SPLITS
                     if getattr(self, name).first <= disbursed_on <= getattr(self, name).last), None)

    def cutoff(self, split: str) -> datetime:
        next_start = {'train': self.calibration.first, 'calibration': self.test.first}.get(split)
        if next_start is None:
            return self.snapshot_at
        return min(self.snapshot_at, datetime.combine(next_start, time.min, tzinfo=BUSINESS_TIMEZONE))


class Facility(Record):
    facility_id: str = Field(pattern=r'^fac_[a-f0-9]{32}$')
    borrower_id: str = Field(pattern=r'^brw_[a-f0-9]{32}$')
    country: Literal['PK']
    product_code: str = Field(min_length=1, max_length=100)
    assessed_at: Timestamp
    disbursed_at: Timestamp
    evidence_available_at: Timestamp | None
    source_review_ref: str | None = Field(min_length=1, max_length=200)
    requested_amount_pkr: float | None = Field(gt=0, le=500_000_000)
    annual_turnover_pkr: float | None = Field(ge=1, le=100_000_000_000)
    payment_history_score: float | None = Field(ge=0, le=100)
    years_in_operation: float | None = Field(ge=0, le=150)
    tenure_months: int | None = Field(ge=3, le=84)
    existing_debt_pkr: float | None = Field(ge=0, le=1_000_000_000)
    inventory_turnover: float | None = Field(ge=0, le=50)
    order_consistency: float | None = Field(ge=0, le=100)
    num_employees: int | None = Field(ge=0, le=5000)

    @property
    def disbursed_on(self):
        return business_date(self.disbursed_at)


class Observation(Record):
    facility_id: str = Field(pattern=r'^fac_[a-f0-9]{32}$')
    observation_date: CalendarDate
    available_at: Timestamp
    days_past_due: int | None = Field(ge=0, le=3650)
    reconciled: Literal['yes', 'no']


class ExportError(ValueError):
    pass


def csv_rows(path, model, label):
    """Yield only the documented fields and keep raw values out of errors."""
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.reader(handle, strict=True)
        header = next(reader, [])
        if len(header) != len(model.model_fields) or set(header) != model.model_fields.keys():
            raise ExportError(f'{label}: headers must match the documented export exactly.')
        for row in reader:
            if not row:
                continue
            if len(row) != len(header):
                raise ExportError(f'{label}: wrong number of columns ending on line {reader.line_num}.')
            try:
                yield reader.line_num, model.model_validate({
                    name: value if value.strip() else None for name, value in zip(header, row, strict=True)
                })
            except ValidationError as error:
                fields = ', '.join(sorted({str(item['loc'][0]) for item in
                                           error.errors(include_input=False, include_context=False, include_url=False)}))
                raise ExportError(f'{label}: invalid {fields} on line {reader.line_num}.') from None


@dataclass
class Candidate:
    facility: Facility
    split: str
    start: date
    end: date
    cutoff: datetime
    days: int = 0
    event: int = 0

    def predictors(self):
        f = self.facility
        return [
            f.requested_amount_pkr / f.annual_turnover_pkr, f.payment_history_score, f.years_in_operation,
            f.tenure_months, f.existing_debt_pkr / f.annual_turnover_pkr,
            f.inventory_turnover, f.order_consistency, f.num_employees,
        ]


def link(protocol, facilities, observations):
    seen = set()
    exclusions = Counter()
    missing_features = Counter()
    candidates = {}
    for line, facility in csv_rows(facilities, Facility, 'Facilities'):
        if facility.facility_id in seen:
            raise ExportError(f'Facilities: duplicate facility on line {line}.')
        seen.add(facility.facility_id)
        if facility.product_code != protocol.product_code:
            raise ExportError(f'Facilities: product outside the approved scope on line {line}.')
        if facility.assessed_at > facility.disbursed_at:
            raise ExportError(f'Facilities: assessment follows disbursement on line {line}.')
        disbursed_on = facility.disbursed_on
        split = protocol.partition(disbursed_on)
        if split is None:
            exclusions['outside_cohort_windows'] += 1
            continue
        if business_date(facility.assessed_at) < getattr(protocol, split).first:
            exclusions['assessment_before_cohort_start'] += 1
            continue
        missing = [name for name in BASE + ADDITIONAL if getattr(facility, name) is None]
        missing_features.update(missing)
        if missing or facility.evidence_available_at is None or facility.source_review_ref is None:
            exclusions['incomplete_features_or_provenance'] += 1
            continue
        if facility.evidence_available_at > facility.assessed_at:
            exclusions['evidence_after_assessment'] += 1
            continue
        cutoff = protocol.cutoff(split)
        if (business_date(cutoff) - disbursed_on).days <= protocol.horizon_days:
            exclusions['outcome_window_open_at_cutoff'] += 1
            continue
        candidates[facility.facility_id] = Candidate(
            facility, split, disbursed_on, disbursed_on + timedelta(days=protocol.horizon_days), cutoff,
        )

    unlinked_rows = 0
    previous = None
    for line, observation in csv_rows(observations, Observation, 'Daily DPD'):
        key = (observation.facility_id, observation.observation_date)
        if previous is not None and key <= previous:
            raise ExportError(f'Daily DPD: duplicate or out-of-order facility/date on line {line}.')
        previous = key
        if business_date(observation.available_at) < observation.observation_date:
            raise ExportError(f'Daily DPD: record availability predates its observation on line {line}.')
        if observation.reconciled == 'yes' and observation.days_past_due is None:
            raise ExportError(f'Daily DPD: reconciled observation needs a DPD value on line {line}.')
        if observation.facility_id not in seen:
            unlinked_rows += 1
            continue
        candidate = candidates.get(observation.facility_id)
        if candidate is None or observation.reconciled != 'yes' or observation.available_at >= candidate.cutoff:
            continue
        if candidate.start < observation.observation_date <= candidate.end:
            if observation.days_past_due > (observation.observation_date - candidate.start).days:
                raise ExportError(f'Daily DPD: arrears predate disbursement on line {line}.')
            candidate.days += 1
            candidate.event |= int(observation.days_past_due >= protocol.event_dpd)

    partitions = {name: [] for name in SPLITS}
    borrower_splits = defaultdict(set)
    for candidate in candidates.values():
        if candidate.days != protocol.horizon_days:
            exclusions['unreconciled_missing_or_late_outcome_days'] += 1
            continue
        partitions[candidate.split].append(candidate)
        borrower_splits[candidate.facility.borrower_id].add(candidate.split)
    counts = {
        name: {'facilities': len(rows), 'events': sum(row.event for row in rows),
               'non_events': sum(1 - row.event for row in rows),
               'borrowers': len({row.facility.borrower_id for row in rows}),
               'event_borrowers': len({row.facility.borrower_id for row in rows if row.event}),
               'non_event_borrowers': len({row.facility.borrower_id for row in rows if not row.event})}
        for name, rows in partitions.items()
    }
    overlap = sum(len(splits) > 1 for splits in borrower_splits.values())
    blockers = []
    if unlinked_rows:
        blockers.append('Daily DPD contains facility IDs absent from the facility export.')
    if overlap:
        blockers.append('Borrower groups overlap across cohorts. Redesign the cohort windows or the authorised population.')
    for name, count in counts.items():
        if min(count['event_borrowers'], count['non_event_borrowers']) < protocol.minimum_per_class:
            blockers.append(f'{name} does not meet the protocol minimum of distinct borrowers for both outcomes.')
    return partitions, {
        'status': 'blocked' if blockers else 'cohort_linked',
        'facilities_in_export': len(seen),
        'cohorts': counts,
        'excluded_facilities': dict(sorted(exclusions.items())),
        'missing_features': dict(sorted(missing_features.items())),
        'unlinked_observation_rows': unlinked_rows,
        'borrowers_in_multiple_cohorts': overlap,
        'blockers': blockers,
    }


def evaluate(partitions):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    features = {name: np.arcsinh([row.predictors() for row in rows])
                for name, rows in partitions.items()}
    labels = {name: np.array([row.event for row in rows]) for name, rows in partitions.items()}
    variants = [('baseline', [0, 1, 2])]
    variants.extend((name, [0, 1, 2, index]) for index, name in enumerate(ADDITIONAL, start=3))
    variants.append(('all_additional_fields', list(range(8))))
    results = {}
    test_scores = {}
    for name, columns in variants:
        model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
        model.fit(features['train'][:, columns], labels['train'])
        # A fixed sigmoid calibrator sees only the separate calibration cohort.
        calibration_scores = model.decision_function(features['calibration'][:, columns]).reshape(-1, 1)
        calibrator = LogisticRegression(max_iter=1000)
        calibrator.fit(calibration_scores, labels['calibration'])
        score = model.decision_function(features['test'][:, columns])
        test_scores[name] = score
        probability = calibrator.predict_proba(score.reshape(-1, 1))[:, 1]
        results[name] = {
            'roc_auc': float(roc_auc_score(labels['test'], score)),
            'average_precision': float(average_precision_score(labels['test'], score)),
            'brier_calibrated': float(brier_score_loss(labels['test'], probability)),
            'mean_calibrated_probability': float(probability.mean()),
            'calibration_preserves_ranking': bool(calibrator.coef_[0, 0] > 0),
        }
    groups = defaultdict(list)
    for index, row in enumerate(partitions['test']):
        groups[row.facility.borrower_id].append(index)
    indices = list(groups.values())
    rng = np.random.default_rng(42)
    deltas = []
    for _ in range(200):
        sample = np.concatenate([indices[index] for index in rng.integers(len(indices), size=len(indices))])
        y = labels['test'][sample]
        if y.min() == y.max():
            continue
        deltas.append(float(roc_auc_score(y, test_scores['all_additional_fields'][sample])
                            - roc_auc_score(y, test_scores['baseline'][sample])))
    interval = [float(value) for value in np.quantile(deltas, [0.025, 0.975])] if len(deltas) >= 160 else None
    return results, {
        'all_fields_minus_baseline_roc_auc': results['all_additional_fields']['roc_auc'] - results['baseline']['roc_auc'],
        'test_borrower_bootstrap_95_percent_interval': interval,
        'usable_bootstrap_samples': len(deltas),
    }


def run(protocol, facilities, observations, *, fit=False):
    partitions, report = link(protocol, facilities, observations)
    report.update({
        'purpose': 'offline_lender_validation',
        'snapshot_at': protocol.snapshot_at.isoformat(),
        'target': {'horizon_days': protocol.horizon_days, 'event_dpd': protocol.event_dpd},
        'minimum_per_class': protocol.minimum_per_class,
        'cohort_windows': {name: getattr(protocol, name).model_dump(mode='json') for name in SPLITS},
    })
    if fit and not report['blockers']:
        report['test_metrics'], report['primary_comparison'] = evaluate(partitions)
        report['status'] = 'evaluated'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('protocol', 'facilities', 'daily-dpd'):
        parser.add_argument(f'--{name}', type=Path, required=True)
    parser.add_argument('--fit', action='store_true', help='Evaluate only after freezing the authorised validation protocol.')
    args = parser.parse_args()
    try:
        protocol = Protocol.model_validate_json(args.protocol.read_bytes())
        report = run(protocol, args.facilities, args.daily_dpd, fit=args.fit)
    except ValidationError:
        parser.exit(2, 'The protocol is invalid. Check the required fields, calendar cutoffs and time offsets.\n')
    except ExportError as error:
        parser.exit(2, f'{error}\n')
    except (OSError, UnicodeError, csv.Error, ValueError):
        parser.exit(2, 'Could not read or evaluate the export. Check the local files and runtime.\n')
    print(json.dumps(report, indent=2, allow_nan=False))
    return 3 if report['blockers'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
