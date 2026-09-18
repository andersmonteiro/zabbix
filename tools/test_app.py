import os
os.environ['TOOLS_TOKEN'] = 'test-token-123'

import importlib
from unittest.mock import patch
import pytest

import app as app_module
importlib.reload(app_module)


@pytest.fixture
def client():
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c


def test_validate_host_accepts_valid_hostname():
    assert app_module.validate_host('example.com') is True


def test_validate_host_accepts_ipv4():
    assert app_module.validate_host('8.8.8.8') is True


def test_validate_host_rejects_empty():
    assert app_module.validate_host('') is False


def test_validate_host_rejects_shell_metacharacters():
    assert app_module.validate_host('8.8.8.8; rm -rf /') is False


def test_validate_host_rejects_leading_dash():
    # host começando com "-" pode ser interpretado como flag pelo mtr/ping/dig
    assert app_module.validate_host('--version') is False


def test_validate_host_rejects_overlong_input():
    assert app_module.validate_host('a' * 300) is False


def test_health_does_not_require_token(client):
    resp = client.get('/health')
    assert resp.status_code == 200


def test_mtr_without_token_returns_401(client):
    resp = client.get('/mtr?host=8.8.8.8')
    assert resp.status_code == 401


def test_mtr_with_invalid_token_returns_401(client):
    resp = client.get('/mtr?host=8.8.8.8', headers={'X-Webhook-Token': 'wrong'})
    assert resp.status_code == 401


def test_mtr_with_valid_token_runs(client):
    with patch.object(app_module, 'run', return_value=('', '')):
        resp = client.get(
            '/mtr?host=8.8.8.8',
            headers={'X-Webhook-Token': 'test-token-123'},
        )
        assert resp.status_code == 200
