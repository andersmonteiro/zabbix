import pytest

from alert_poller import AlertCache, fetch_problems
from zabbix_client import ZabbixClient

ZABBIX_URL = 'http://zabbix-frontend:8080'
API = f'{ZABBIX_URL}/api_jsonrpc.php'


@pytest.fixture
def zabbix_client():
    return ZabbixClient(ZABBIX_URL, 'Admin', 'secret')


def _login_response():
    return {'json': {'jsonrpc': '2.0', 'result': 'authtoken123', 'id': 1}}


def test_fetch_problems_serializes_host_and_severity_label(zabbix_client, requests_mock):
    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': [{
            'eventid': '501', 'name': 'Link down', 'severity': '4', 'clock': '1700000000',
            'acknowledged': '0', 'object': '0', 'objectid': '77',
        }]}},
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': [
            {'triggerid': '77', 'hosts': [{'name': 'DTC - CARACOL - 6'}]},
        ]}},
    ])

    problems = fetch_problems(zabbix_client)

    assert problems == [{
        'eventid': '501', 'name': 'Link down', 'host': 'DTC - CARACOL - 6',
        'severity': 4, 'severity_label': 'Alta', 'clock': 1700000000, 'acknowledged': False,
    }]


def test_fetch_problems_sorts_by_severity_then_recency(zabbix_client, requests_mock):
    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': [
            {'eventid': '1', 'name': 'old high', 'severity': '4', 'clock': '100', 'acknowledged': '0', 'object': '0', 'objectid': '1'},
            {'eventid': '2', 'name': 'disaster', 'severity': '5', 'clock': '50', 'acknowledged': '0', 'object': '0', 'objectid': '2'},
            {'eventid': '3', 'name': 'new high', 'severity': '4', 'clock': '200', 'acknowledged': '0', 'object': '0', 'objectid': '3'},
        ]}},
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': []}},
    ])

    problems = fetch_problems(zabbix_client)

    assert [p['eventid'] for p in problems] == ['2', '3', '1']


def test_fetch_problems_defaults_host_to_dash_when_trigger_has_no_host(zabbix_client, requests_mock):
    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': [{
            'eventid': '9', 'name': 'orphan trigger', 'severity': '2', 'clock': '1',
            'acknowledged': '1', 'object': '0', 'objectid': '55',
        }]}},
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': [{'triggerid': '55', 'hosts': []}]}},
    ])

    problems = fetch_problems(zabbix_client)
    assert problems[0]['host'] == '—'
    assert problems[0]['acknowledged'] is True


def test_fetch_problems_skips_trigger_lookup_when_no_problems(zabbix_client, requests_mock):
    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': []}},
    ])

    assert fetch_problems(zabbix_client) == []


def test_alert_cache_starts_empty_and_unset():
    cache = AlertCache()
    assert cache.get_all() == []
    assert cache.last_refresh() is None


def test_alert_cache_update_replaces_problems_and_sets_refresh_time():
    cache = AlertCache()
    cache.update([{'eventid': '1'}])
    assert cache.get_all() == [{'eventid': '1'}]
    assert cache.last_refresh() is not None
