import time

import pytest
from flask import Flask

from alert_poller import AlertCache
from routes_alerts import alerts_bp, init_alerts_routes


@pytest.fixture
def cache():
    return AlertCache()


@pytest.fixture
def client(cache):
    app = Flask(__name__)
    init_alerts_routes(cache, stale_threshold_seconds=120)
    app.register_blueprint(alerts_bp)
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def test_list_alerts_returns_problems_when_cache_fresh(client, cache):
    cache.update([{'eventid': '1', 'name': 'Link down', 'severity': 4}])

    resp = client.get('/api/alerts')

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['stale'] is False
    assert body['problems'] == [{'eventid': '1', 'name': 'Link down', 'severity': 4}]
    assert 0 <= body['last_refresh_seconds_ago'] < 5


def test_list_alerts_reports_stale_and_hides_problems_when_cache_old(client, cache):
    cache.update([{'eventid': '1', 'name': 'Link down', 'severity': 4}])
    cache._last_refresh = time.time() - 999

    resp = client.get('/api/alerts')

    body = resp.get_json()
    assert body['stale'] is True
    assert body['problems'] == []


def test_list_alerts_stale_when_never_refreshed(client):
    resp = client.get('/api/alerts')
    body = resp.get_json()
    assert body['stale'] is True
    assert body['last_refresh_seconds_ago'] is None
    assert body['problems'] == []
