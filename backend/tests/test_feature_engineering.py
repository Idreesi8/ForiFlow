"""Feature research isolation, reproducibility and categorical integrity."""
import copy

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from ml import feature_engineering as study
from ml import pipeline as protocol


def sample(n=160):
    rng = np.random.default_rng(8)
    X = pd.DataFrame({'loan_to_income': rng.uniform(.02, .8, n),
                      'payment_history_score': rng.choice([25., 80.], n),
                      'years_in_operation': rng.uniform(0, 20, n)}, index=np.arange(2000, 2000+n))
    y = pd.Series((np.arange(n) % 4 == 0).astype(int), index=X.index)
    X.loc[X.index[0], 'years_in_operation'] = np.nan
    return X, y


def test_fixed_features_have_correct_units_interactions_and_no_target_input():
    X = np.array([[.5, 25, 3], [0, 80, 0], [.5, 80, 3]])
    actual = study.ResearchFeatures().fit_transform(X)
    assert actual.shape == (3, 5) and np.isfinite(actual).all()
    assert actual[0] == pytest.approx([np.log1p(.5), 1, np.log(4), np.log1p(.5), np.log1p(.5)/4])
    assert np.array_equal(actual[1], np.zeros(5))
    assert actual[2, 3] == 0
    assert study.ResearchFeatures().transform(X).tolist() == actual.tolist()


@pytest.mark.parametrize('values', [np.zeros((2, 4)), [[-.1, 25, 2]], [[.1, 80, -1]], [[.1, np.nan, 1]], [[np.inf, 25, 1]]])
def test_engineering_rejects_invalid_or_wrong_contract(values):
    with pytest.raises(ValueError): study.ResearchFeatures().fit_transform(values)


def test_categorical_sampling_preserves_only_observed_history_levels():
    X, y = sample()
    learner = study.fit_candidate('logistic_smotenc', X, y)
    scaler = learner.named_steps['sampling_scale']
    clean = learner.named_steps['preprocess'].transform(X)
    generated, _ = learner.named_steps['sample'].fit_resample(scaler.transform(clean), y)
    recovered = scaler.inverse_transform(generated)[:, 1]
    assert all(min(abs(value-25), abs(value-80)) < 1e-7 for value in recovered)


def test_engineering_occurs_after_sampling_and_inverse_scaling():
    X, y = sample()
    learner = study.fit_candidate('engineered_logistic_smotenc', X, y)
    assert list(learner.named_steps) == ['preprocess', 'sampling_scale', 'sample', 'unscale', 'engineer', 'model_scale', 'model']
    clean = learner.named_steps['preprocess'].transform(X)
    reconstructed = learner.named_steps['unscale'].transform(learner.named_steps['sampling_scale'].transform(clean))
    assert reconstructed == pytest.approx(clean)
    assert np.isfinite(learner.predict_proba(X)).all()


def test_heldout_extremes_cannot_change_engineering_fit_or_preprocessing():
    X, y = sample()
    learner = study.fit_candidate('engineered_logistic_smotenc', X.iloc[:120], y.iloc[:120])
    before = copy.deepcopy(learner.named_steps['preprocess'].clips_)
    medians = copy.deepcopy(learner.named_steps['preprocess'].medians_)
    heldout = X.iloc[120:].copy()
    heldout.iloc[:, 0] = 1e9
    heldout.iloc[:, 2] = np.nan
    assert np.isfinite(learner.predict_proba(heldout)).all()
    assert learner.named_steps['preprocess'].clips_ == before
    assert learner.named_steps['preprocess'].medians_ == medians
    assert learner.named_steps['preprocess'].n_fit_rows_ == 120


def test_cv_fits_only_fit_rows_and_scores_every_row_once(monkeypatch):
    X, y = sample(200)
    seen = []
    original = protocol.TrainOnlyPreprocessor.fit
    def spy(self, frame, y=None):
        seen.append(set(frame.index))
        return original(self, frame, y)
    monkeypatch.setattr(protocol.TrainOnlyPreprocessor, 'fit', spy)
    result = study.run_cv(X, y, candidates=['logistic_smotenc'], folds=4, on_progress=lambda *a, **kw: None)
    assert len(seen) == 4 and all(len(rows) == 150 for rows in seen)
    assert all(sum(row not in fit for fit in seen) == 1 for row in X.index)
    assert result['candidates'][0]['oof']['rows'] == 200
    assert len(result['folds']) == 4


def test_cv_rejects_labels_with_wrong_row_alignment():
    X, y = sample()
    with pytest.raises(ValueError): study.run_cv(X, y.iloc[::-1])


def test_reference_guard_rejects_altered_source_and_partitions():
    X, y = sample()
    frame = X.assign(target=y)
    split = protocol.split_rows(frame)
    prepared = protocol.Prepared(frame, frame, 'known', len(frame))
    metadata = {'dataset_sha256': 'known', 'feature_names': study.FEATURES,
                'split': {'id_sha256': split.describe(frame)['id_sha256']}}
    study.check_reference(prepared, split, metadata)
    wrong = copy.deepcopy(metadata); wrong['dataset_sha256'] = 'other'
    with pytest.raises(ValueError): study.check_reference(prepared, split, wrong)
    wrong = copy.deepcopy(metadata); wrong['split']['id_sha256']['train'] = 'other'
    with pytest.raises(ValueError): study.check_reference(prepared, split, wrong)


def test_information_collision_counts_do_not_treat_conflicts_as_bad_labels():
    X = pd.DataFrame([[.1, 25., 1.]] * 4 + [[.2, 80., 2.]] * 2, columns=study.FEATURES)
    y = pd.Series([0, 1, 0, 1, 0, 0])
    raw = pd.DataFrame({'cb_person_default_on_file': ['Y'] * 4 + ['N'] * 2})
    result = study.training_diagnostics(X, y, raw)
    assert result['unique_model_vectors'] == 2
    assert result['rows_in_repeated_vectors'] == 6
    assert result['rows_in_conflicting_vectors'] == 4
    assert result['conflicting_vectors'] == 1


def test_unknown_candidate_is_rejected():
    with pytest.raises(ValueError): study.build_candidate('invented')
