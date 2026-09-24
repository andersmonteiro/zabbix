import pytest
from flask import Flask

from models import Base, Circuit, Point, Segment, get_engine, get_session_factory
from routes_history import history_bp, init_history_routes
from zabbix_client import ZabbixClient

ZABBIX_URL = 'http://zabbix-frontend:8080'
API = f'{ZABBIX_URL}/api_jsonrpc.php'


@pytest.fixture
def session_factory():
    engine = get_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return get_session_factory(engine)


@pytest.fixture
def segment(session_factory):
    session = session_factory()
    origin = Point(name='A', lat=-8.0, lng=-55.0, point_type='equipment')
    dest = Point(name='B', lat=-8.1, lng=-55.1, point_type='equipment')
    session.add_all([origin, dest])
    session.commit()
    circuit = Circuit(name='Circuito teste')
    session.add(circuit)
    session.commit()
    seg = Segment(
        circuit_id=circuit.id, order_index=0,
        origin_point_id=origin.id, destination_point_id=dest.id, waypoint_ids=[],
        zabbix_throughput_in_itemid='70001', zabbix_throughput_out_itemid='70002',
    )
    session.add(seg)
    session.commit()
    segment_id = seg.id
    session.close()
    return segment_id


@pytest.fixture
def client(session_factory):
    zabbix_client = ZabbixClient(ZABBIX_URL, 'Admin', 'secret')
    app = Flask(__name__)
    init_history_routes(session_factory, zabbix_client)
    app.register_blueprint(history_bp)
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def _login_response():
    return {'json': {'jsonrpc': '2.0', 'result': 'authtoken123', 'id': 1}}


def test_segment_history_returns_mbps_series_for_both_directions(client, segment, requests_mock):
    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': [{'value_type': '3'}]}},  # item.get for IN
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': [  # history.get for IN
            {'clock': '1000', 'value': '1000000000'},
            {'clock': '1300', 'value': '2000000000'},
        ]}},
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': [{'value_type': '3'}]}},  # item.get for OUT
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': [  # history.get for OUT
            {'clock': '1000', 'value': '500000000'},
        ]}},
    ])

    resp = client.get(f'/api/segments/{segment}/history?hours=6')

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['hours'] == 6
    assert body['throughput_in_mbps'] == [[1000, 1000.0], [1300, 2000.0]]
    assert body['throughput_out_mbps'] == [[1000, 500.0]]


def test_segment_history_returns_404_for_missing_segment(client):
    resp = client.get('/api/segments/9999/history')
    assert resp.status_code == 404


def test_segment_history_clamps_hours_to_allowed_range(client, segment, requests_mock):
    requests_mock.post(API, [
        _login_response(),
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': [{'value_type': '3'}]}},
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': []}},
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': [{'value_type': '3'}]}},
        {'json': {'jsonrpc': '2.0', 'id': 3, 'result': []}},
    ])

    resp = client.get(f'/api/segments/{segment}/history?hours=99999')
    assert resp.get_json()['hours'] == 168


def test_segment_history_returns_502_on_zabbix_failure(client, segment, requests_mock):
    requests_mock.post(API, exc=__import__('requests').exceptions.ConnectionError('refused'))
    resp = client.get(f'/api/segments/{segment}/history')
    assert resp.status_code == 502
    assert 'error' in resp.get_json()
