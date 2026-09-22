import json

import pytest
from flask import Flask

from routes_hosts import hosts_bp, init_hosts_routes
from zabbix_client import ZabbixClient

ZABBIX_URL = 'http://zabbix-frontend:8080'
API = f'{ZABBIX_URL}/api_jsonrpc.php'


@pytest.fixture
def client():
    zabbix_client = ZabbixClient(ZABBIX_URL, 'Admin', 'secret')
    app = Flask(__name__)
    init_hosts_routes(zabbix_client)
    app.register_blueprint(hosts_bp)
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def _login_response():
    return {'json': {'jsonrpc': '2.0', 'result': 'authtoken123', 'id': 1}}


def test_list_hosts_serializes_interfaces_groups_and_macros(client, requests_mock):
    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 2, 'result': [{
            'hostid': '100', 'host': 'SW-TESTE', 'status': '0',
            'interfaces': [{'ip': '10.0.0.5', 'port': '161', 'details': {'community': 'public'}}],
            'hostgroups': [{'name': 'SWITCHS'}],
            'macros': [
                {'macro': '{$VENDOR}', 'value': 'huawei'},
                {'macro': '{$SSH_USER}', 'value': 'monitor'},
            ],
        }]}},
    ])

    resp = client.get('/api/zabbix/hosts')
    assert resp.status_code == 200
    hosts = resp.get_json()
    assert hosts == [{
        'hostid': '100', 'host': 'SW-TESTE', 'ip': '10.0.0.5', 'port': '161',
        'community': 'public', 'groups': ['SWITCHS'], 'vendor': 'huawei', 'model': '',
        'ssh_user': 'monitor', 'ssh_port': '', 'status': 'enabled',
    }]


def test_list_hosts_returns_502_on_zabbix_connection_failure(client, requests_mock):
    requests_mock.post(API, exc=__import__('requests').exceptions.ConnectionError('refused'))
    resp = client.get('/api/zabbix/hosts')
    assert resp.status_code == 502
    assert 'error' in resp.get_json()


def test_create_host_applies_default_community_and_port(client, requests_mock):
    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': {'hostids': ['501']}}},
    ])

    resp = client.post('/api/zabbix/hosts', json={'name': 'Novo Host', 'ip': '10.0.0.9', 'group_id': '5'})
    assert resp.status_code == 201
    assert resp.get_json() == {'hostid': '501'}

    sent = json.loads(requests_mock.request_history[-1].body)
    params = sent['params']
    assert params['host'] == 'Novo Host'
    assert params['interfaces'][0]['ip'] == '10.0.0.9'
    assert params['interfaces'][0]['details']['community'] == 'public'
    assert params['interfaces'][0]['port'] == '161'
    macro_values = {m['macro']: m['value'] for m in params['macros']}
    assert macro_values['{$SNMP_COMMUNITY}'] == 'public'
    assert macro_values['{$SNMP_PORT}'] == '161'


def test_create_host_requires_name_ip_and_group(client):
    resp = client.post('/api/zabbix/hosts', json={'name': 'Sem IP'})
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


def test_create_host_resolves_vendor_template_set(client, requests_mock):
    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': [
            {'templateid': '900', 'name': 'MW - MIKROTIK - HEALTH'},
            {'templateid': '901', 'name': 'MW - MIKROTIK - SFP'},
        ]}},
        {'json': {'jsonrpc': '2.0', 'id': 4, 'result': {'hostids': ['502']}}},
    ])

    resp = client.post('/api/zabbix/hosts', json={
        'name': 'SW Mikrotik', 'ip': '10.0.0.10', 'group_id': '5', 'vendor': 'mikrotik',
    })
    assert resp.status_code == 201

    create_call = json.loads(requests_mock.request_history[-1].body)
    template_ids = {t['templateid'] for t in create_call['params']['templates']}
    assert template_ids == {'900', '901'}


def test_delete_host(client, requests_mock):
    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': {'hostids': ['100']}}},
    ])
    resp = client.delete('/api/zabbix/hosts/100')
    assert resp.status_code == 204
