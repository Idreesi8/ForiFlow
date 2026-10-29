"""Inference loading preserves model bytes and predictions across platforms."""
from __future__ import annotations

import struct

import joblib
import numpy as np
import pytest
import xgboost

from ml.artifact_loader import (
    SnapshotFormatError,
    load_inference_artifact,
    snapshot_model_bytes,
)


def _key(name: str) -> bytes:
    encoded = name.encode()
    return b'U' + bytes([len(encoded)]) + encoded


def _object(pairs: list[tuple[str, bytes]]) -> bytes:
    return b'{' + b''.join(_key(key) + value for key, value in pairs) + b'}'


@pytest.mark.parametrize('config', [
    b'F', b'T', b'Z', b'Cz', b'd' + struct.pack('>f', 0.125),
    b'SU\x03rng', b'[U\x01U\x02]', b'[$d#U\x02' + struct.pack('>ff', 0.125, -3.75),
    _object([('nested', _object([('Model', b'{}')]))]),
])
def test_model_bytes_are_kept_exactly_and_config_is_not_restored(config: bytes) -> None:
    model = _object([('learner', _object([('threshold', b'd' + struct.pack('>f', 0.375))]))])
    snapshot = _object([('Config', config), ('Model', model)])
    assert snapshot_model_bytes(snapshot) == model


@pytest.mark.parametrize('snapshot', [
    b'', b'binf', b'{}', _object([('Model', b'F')]),
    _object([('Model', b'{}'), ('Model', b'{}')]),
    _object([('Model', b'{}')]) + b'junk',
    _object([('Config', b'SU\x07x'), ('Model', b'{}')]),
    _object([('Config', b'[$d#i\xff'), ('Model', b'{}')]),
])
def test_unknown_or_malformed_snapshots_fail_instead_of_inventing_a_model(snapshot: bytes) -> None:
    with pytest.raises(SnapshotFormatError):
        snapshot_model_bytes(snapshot)


def test_supported_model_io_preserves_predictions_contributions_and_feature_metadata(tmp_path) -> None:
    rng = np.random.default_rng(42)
    values = rng.normal(size=(80, 3))
    matrix = xgboost.DMatrix(values, label=(values[:, 0] > values[:, 1]).astype(int),
                             feature_names=['receipts', 'debt', 'history'])
    booster = xgboost.train(
        {'objective': 'binary:logistic', 'seed': 19, 'nthread': 1, 'max_depth': 2},
        matrix, num_boost_round=4,
    )
    booster.set_attr(provenance='parity-test')
    artifact = tmp_path / 'trusted.pkl'
    joblib.dump({'model': booster, 'reference': np.arange(3)}, artifact)
    original_restore = xgboost.Booster.__setstate__

    loaded = load_inference_artifact(artifact)

    np.testing.assert_array_equal(loaded['model'].predict(matrix), booster.predict(matrix))
    np.testing.assert_array_equal(
        loaded['model'].predict(matrix, pred_contribs=True),
        booster.predict(matrix, pred_contribs=True),
    )
    assert loaded['model'].save_raw(raw_format='ubj') == booster.save_raw(raw_format='ubj')
    assert loaded['model'].feature_names == booster.feature_names
    assert loaded['model'].attributes() == booster.attributes()
    np.testing.assert_array_equal(loaded['reference'], np.arange(3))
    assert xgboost.Booster.__setstate__ is original_restore
