"""Production cannot silently start with an unintended demonstration fallback."""
import pytest
from fastapi.testclient import TestClient

import main
from services.scoring_service import _fallback
from services.security_config import ConfigurationReport


@pytest.mark.parametrize('reason', ['artifacts_missing', 'load_failed'])
def test_production_refuses_an_unintended_scoring_fallback(monkeypatch, reason) -> None:
    monkeypatch.setattr(main, 'configuration_report', lambda: ConfigurationReport('production'))
    monkeypatch.setattr(main, 'init_db', lambda: None)
    monkeypatch.setattr(main, 'get_scoring_service', lambda: _fallback(reason))
    with pytest.raises(main.UnsafeConfiguration, match='unintended scoring fallback'):
        with TestClient(main.create_app()):
            pytest.fail('An unavailable trained model cannot start production.')
