import json

import pytest
from flask import Flask

from models import Base, Point, get_engine, get_session_factory
from routes_hosts import hosts_bp, init_hosts_routes
from zabbix_client import ZabbixClient

ZABBIX_URL = 'http://zabbix-frontend:8080'
API = f'{ZABBIX_URL}/api_jsonrpc.php'


@pytest.fixture
def client_and_sessions():
    zabbix_client = ZabbixClient(ZABBIX_URL, 'Admin', 'secret')
    engine = get_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)

    app = Flask(__name__)
    init_hosts_routes(zabbix_client, session_factory)
    app.register_blueprint(hosts_bp)
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c, session_factory


@pytest.fixture
def client(client_and_sessions):
    return client_and_sessions[0]


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
        'lat': None, 'lng': None,
    }]


def test_list_hosts_includes_coordinates_of_a_linked_point(client_and_sessions, requests_mock):
    client, session_factory = client_and_sessions
    session = session_factory()
    session.add(Point(name='SW-TESTE', lat=-8.3, lng=-55.4, point_type='equipment', zabbix_hostid='100'))
    session.commit()
    session.close()

    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 2, 'result': [{
            'hostid': '100', 'host': 'SW-TESTE', 'status': '0', 'interfaces': [], 'hostgroups': [], 'macros': [],
        }]}},
    ])

    resp = client.get('/api/zabbix/hosts')
    host = resp.get_json()[0]
    assert host['lat'] == -8.3
    assert host['lng'] == -55.4


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


def test_create_host_with_coordinates_creates_a_linked_point(client_and_sessions, requests_mock):
    client, session_factory = client_and_sessions
    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': {'hostids': ['503']}}},
    ])

    resp = client.post('/api/zabbix/hosts', json={
        'name': 'SW Coords', 'ip': '10.0.0.11', 'group_id': '5', 'lat': -8.3, 'lng': -55.4,
    })
    assert resp.status_code == 201

    session = session_factory()
    point = session.query(Point).filter(Point.zabbix_hostid == '503').one()
    assert point.lat == -8.3
    assert point.lng == -55.4
    assert point.point_type == 'equipment'
    session.close()


def test_create_host_without_coordinates_creates_no_point(client_and_sessions, requests_mock):
    client, session_factory = client_and_sessions
    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': {'hostids': ['504']}}},
    ])

    resp = client.post('/api/zabbix/hosts', json={'name': 'Sem Coords', 'ip': '10.0.0.12', 'group_id': '5'})
    assert resp.status_code == 201

    session = session_factory()
    assert session.query(Point).filter(Point.zabbix_hostid == '504').first() is None
    session.close()


def test_update_host_sends_full_macro_set_and_new_interface(client, requests_mock):
    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 2, 'result': [
            {'hostid': '100', 'interfaces': [{'interfaceid': '10'}]},
        ]}},
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': {'hostids': ['100']}}},
    ])

    resp = client.put('/api/zabbix/hosts/100', json={
        'name': 'SW Renomeado', 'ip': '10.0.0.20', 'group_id': '5',
        'vendor': 'huawei', 'community': 'privado', 'port': '162',
    })
    assert resp.status_code == 200

    update_call = json.loads(requests_mock.request_history[-1].body)
    params = update_call['params']
    assert params['hostid'] == '100'
    assert params['host'] == 'SW Renomeado'
    assert params['interfaces'][0]['interfaceid'] == '10'
    assert params['interfaces'][0]['ip'] == '10.0.0.20'
    assert params['interfaces'][0]['details']['community'] == 'privado'
    macro_values = {m['macro']: m['value'] for m in params['macros']}
    assert macro_values['{$SNMP_COMMUNITY}'] == 'privado'
    assert macro_values['{$SNMP_PORT}'] == '162'
    assert macro_values['{$VENDOR}'] == 'huawei'


def test_update_host_upserts_the_linked_point_coordinates(client_and_sessions, requests_mock):
    client, session_factory = client_and_sessions
    session = session_factory()
    session.add(Point(name='SW-TESTE', lat=-8.0, lng=-55.0, point_type='equipment', zabbix_hostid='100'))
    session.commit()
    session.close()

    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 2, 'result': [
            {'hostid': '100', 'interfaces': [{'interfaceid': '10'}]},
        ]}},
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': {'hostids': ['100']}}},
    ])

    resp = client.put('/api/zabbix/hosts/100', json={'lat': -9.5, 'lng': -56.5})
    assert resp.status_code == 200

    session = session_factory()
    point = session.query(Point).filter(Point.zabbix_hostid == '100').one()
    assert point.lat == -9.5
    assert point.lng == -56.5
    session.close()


def test_update_host_returns_404_when_host_missing(client, requests_mock):
    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 2, 'result': []}},
    ])
    resp = client.put('/api/zabbix/hosts/999', json={'name': 'X'})
    assert resp.status_code == 404


def test_delete_host(client, requests_mock):
    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': {'hostids': ['100']}}},
    ])
    resp = client.delete('/api/zabbix/hosts/100')
    assert resp.status_code == 204
