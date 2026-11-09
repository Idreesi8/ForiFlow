import csv
from datetime import date, timedelta
import json

import pytest
from pydantic import ValidationError

from ml.pilot_validation import ADDITIONAL, SPLITS, ExportError, Facility, Observation, Protocol, run


def identifier(prefix, number):
    return f'{prefix}_{number:032x}'


@pytest.fixture
def pilot(tmp_path):
    # Fictional cohorts with an intentionally short horizon for contract testing.
    protocol = Protocol.model_validate({
        'schema_version': 1, 'country': 'PK', 'product_code': 'fictional-product',
        'target_definition_ref': 'fictional-target', 'training_authority_ref': 'fictional-authority',
        'snapshot_at': '2025-05-01T00:00:00+05:00', 'horizon_days': 2, 'event_dpd': 1,
        'minimum_per_class': 2,
        **{split: {'first': f'2025-0{month}-01', 'last': f'2025-0{month}-15'}
           for month, split in enumerate(SPLITS, 1)},
    })
    facilities = []
    observations = []
    for month in range(1, 4):
        disbursed = date(2025, month, 3)
        for offset in range(4):
            index = month * 10 + offset
            facility_id = identifier('fac', index)
            facilities.append({
                'facility_id': facility_id, 'borrower_id': identifier('brw', index),
                'country': 'PK', 'product_code': protocol.product_code,
                'assessed_at': f'{disbursed}T09:00:00+05:00',
                'disbursed_at': f'{disbursed}T15:00:00+05:00',
                'evidence_available_at': f'{disbursed}T08:00:00+05:00', 'source_review_ref': 'fictional-review',
                'requested_amount_pkr': 300_000 + offset * 10_000, 'annual_turnover_pkr': 2_000_000,
                'payment_history_score': 80, 'years_in_operation': 4, 'tenure_months': 12,
                'existing_debt_pkr': 200_000, 'inventory_turnover': 5,
                'order_consistency': 30 if offset < 2 else 85, 'num_employees': 4,
            })
            for number in (1, 2):
                day = disbursed + timedelta(days=number)
                observations.append({
                    'facility_id': facility_id, 'observation_date': day,
                    'available_at': f'{day}T23:00:00+05:00', 'reconciled': 'yes',
                    'days_past_due': 1 if offset < 2 and number == 2 else 0,
                })

    def verify(*, fit=False):
        files = []
        for model, rows in ((Facility, facilities), (Observation, observations)):
            path = tmp_path / f'{model.__name__}.csv'
            with path.open('w', encoding='utf-8', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=model.model_fields.keys())
                writer.writeheader()
                writer.writerows(rows)
            files.append(path)
        return run(protocol, *files, fit=fit)

    return facilities, observations, verify


def test_link_then_fit_separate_cohorts(pilot):
    facilities, _, verify = pilot
    audit = verify()
    assert audit['status'] == 'cohort_linked'
    assert 'test_metrics' not in audit
    report = verify(fit=True)
    assert report['status'] == 'evaluated'
    assert all(report['cohorts'][split]['events'] == 2 for split in SPLITS)
    assert set(report['test_metrics']) == {'baseline', 'all_additional_fields', *ADDITIONAL}
    assert all(0 <= variant['brier_calibrated'] <= 1 for variant in report['test_metrics'].values())
    comparison = report['primary_comparison']
    assert comparison['usable_bootstrap_samples'] >= 160
    assert len(comparison['test_borrower_bootstrap_95_percent_interval']) == 2
    encoded = json.dumps(report, allow_nan=False)
    assert facilities[0]['borrower_id'] not in encoded
    assert facilities[0]['facility_id'] not in encoded
    assert facilities[0]['source_review_ref'] not in encoded


def test_refuses_late_features_unreconciled_days_and_late_labels(pilot):
    facilities, observations, verify = pilot
    facilities[0]['evidence_available_at'] = '2025-01-03T10:00:00+05:00'
    observations[9]['reconciled'] = 'no'
    # This completed calibration observation arrived at the test boundary.
    observations[11]['available_at'] = '2025-03-01T00:00:00+05:00'
    report = verify(fit=True)
    assert report['status'] == 'blocked'
    assert report['excluded_facilities'] == {
        'evidence_after_assessment': 1, 'unreconciled_missing_or_late_outcome_days': 2,
    }
    assert report['cohorts']['calibration']['events'] == 0
    assert 'test_metrics' not in report


def test_repeats_cannot_cross_splits_or_inflate_borrower_minimum(pilot):
    facilities, _, verify = pilot
    facilities[1]['borrower_id'] = facilities[0]['borrower_id']
    facilities[-1]['borrower_id'] = facilities[0]['borrower_id']
    report = verify(fit=True)
    assert report['status'] == 'blocked'
    assert report['borrowers_in_multiple_cohorts'] == 1
    assert report['cohorts']['train']['events'] == 2
    assert report['cohorts']['train']['event_borrowers'] == 1
    assert len(report['blockers']) == 2


def test_requires_unique_daily_observation_and_matching_facilities(pilot):
    _, observations, verify = pilot
    observations.append({**observations[-1], 'facility_id': identifier('fac', 99)})
    report = verify()
    assert report['status'] == 'blocked'
    assert report['unlinked_observation_rows'] == 1
    observations.insert(1, observations[0])
    with pytest.raises(ExportError, match='duplicate or out-of-order'):
        verify()


def test_requires_point_in_time_dates_and_sanitises_bad_fields(pilot):
    facilities, _, verify = pilot
    facilities[0]['evidence_available_at'] = '1735872000'
    with pytest.raises(ExportError, match='invalid evidence_available_at on line 2') as error:
        verify()
    assert '1735872000' not in str(error.value)
    facilities[0]['evidence_available_at'] = '2025-01-03T08:00:00+05:00'
    facilities[0]['disbursed_at'] = '2025-01-03T08:30:00+05:00'
    with pytest.raises(ExportError, match='assessment follows disbursement'):
        verify()
    with pytest.raises(ValidationError):
        Observation.model_validate({
            'facility_id': identifier('fac', 10), 'observation_date': '20250104',
            'available_at': '2025-01-04T23:00:00', 'days_past_due': 0, 'reconciled': 'yes',
        })


def test_rejects_arrears_that_predate_a_new_disbursement(pilot):
    _, observations, verify = pilot
    observations[0]['days_past_due'] = 30
    with pytest.raises(ExportError, match='arrears predate disbursement'):
        verify()


def test_later_disbursement_cannot_hide_an_assessment_before_the_split(pilot):
    facilities, _, verify = pilot
    facilities[-1]['assessed_at'] = '2025-02-28T21:00:00+05:00'
    facilities[-1]['evidence_available_at'] = '2025-02-28T20:00:00+05:00'
    report = verify(fit=True)
    assert report['status'] == 'blocked'
    assert report['excluded_facilities'] == {'assessment_before_cohort_start': 1}
    assert 'test_metrics' not in report
