import pytest
from flask import Flask

from models import Base, Point, get_engine, get_session_factory
from routes_points import points_bp, init_points_routes
from routes_circuits import circuits_bp, init_circuits_routes


@pytest.fixture
def client():
    engine = get_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)

    app = Flask(__name__)
    init_points_routes(session_factory)
    init_circuits_routes(session_factory)
    app.register_blueprint(points_bp)
    app.register_blueprint(circuits_bp)
    app.config['TESTING'] = True

    session = session_factory()
    session.add_all([
        Point(id=1, name='POP Centro', lat=-23.5605, lng=-46.6580, point_type='equipment'),
        Point(id=2, name='Cliente Av. Brasil', lat=-23.5560, lng=-46.6460, point_type='equipment'),
        Point(id=3, name='Poste 12', lat=-23.559, lng=-46.650, point_type='waypoint'),
    ])
    session.commit()
    session.close()

    with app.test_client() as c:
        yield c


def test_create_circuit(client):
    resp = client.post('/api/circuits', json={'name': 'POP Centro -> Cliente'})
    assert resp.status_code == 201
    assert resp.get_json()['name'] == 'POP Centro -> Cliente'


def test_create_segment_under_circuit(client):
    circuit = client.post('/api/circuits', json={'name': 'POP Centro -> Cliente'}).get_json()

    resp = client.post(f"/api/circuits/{circuit['id']}/segments", json={
        'order_index': 0, 'origin_point_id': 1, 'destination_point_id': 2,
        'waypoint_ids': [3], 'zabbix_operstatus_itemid': '55010',
        'zabbix_optical_rx_itemid': '55011', 'signal_warn_threshold_dbm': -25.0,
    })
    assert resp.status_code == 201
    segment = resp.get_json()
    assert segment['waypoint_ids'] == [3]
    assert segment['signal_warn_threshold_dbm'] == -25.0


def test_segment_round_trips_side_b_itemids(client):
    circuit = client.post('/api/circuits', json={'name': 'POP Centro -> Cliente'}).get_json()

    resp = client.post(f"/api/circuits/{circuit['id']}/segments", json={
        'order_index': 0, 'origin_point_id': 1, 'destination_point_id': 2,
        'zabbix_operstatus_itemid': '55010', 'zabbix_optical_rx_itemid': '55011',
        'zabbix_operstatus_itemid_b': '55020', 'zabbix_optical_rx_itemid_b': '55021',
        'zabbix_optical_tx_itemid_b': '55022', 'zabbix_throughput_in_itemid_b': '55023',
        'zabbix_throughput_out_itemid_b': '55024', 'zabbix_speed_itemid_b': '55025',
    })
    assert resp.status_code == 201
    segment = resp.get_json()
    assert segment['zabbix_operstatus_itemid_b'] == '55020'
    assert segment['zabbix_optical_rx_itemid_b'] == '55021'
    assert segment['zabbix_optical_tx_itemid_b'] == '55022'
    assert segment['zabbix_throughput_in_itemid_b'] == '55023'
    assert segment['zabbix_throughput_out_itemid_b'] == '55024'
    assert segment['zabbix_speed_itemid_b'] == '55025'

    resp = client.put(f"/api/segments/{segment['id']}", json={'zabbix_optical_rx_itemid_b': '55099'})
    assert resp.status_code == 200
    assert resp.get_json()['zabbix_optical_rx_itemid_b'] == '55099'


def test_get_circuit_includes_segments(client):
    circuit = client.post('/api/circuits', json={'name': 'POP Centro -> Cliente'}).get_json()
    client.post(f"/api/circuits/{circuit['id']}/segments", json={
        'order_index': 0, 'origin_point_id': 1, 'destination_point_id': 2, 'waypoint_ids': [3],
    })

    resp = client.get(f"/api/circuits/{circuit['id']}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body['segments']) == 1
    assert body['segments'][0]['origin_point_id'] == 1


def test_segment_rejects_unknown_point_reference(client):
    circuit = client.post('/api/circuits', json={'name': 'X'}).get_json()
    resp = client.post(f"/api/circuits/{circuit['id']}/segments", json={
        'order_index': 0, 'origin_point_id': 999, 'destination_point_id': 2, 'waypoint_ids': [],
    })
    assert resp.status_code == 400


def test_update_segment_waypoints_for_path_editing(client):
    circuit = client.post('/api/circuits', json={'name': 'X'}).get_json()
    segment = client.post(f"/api/circuits/{circuit['id']}/segments", json={
        'order_index': 0, 'origin_point_id': 1, 'destination_point_id': 2, 'waypoint_ids': [3],
    }).get_json()

    resp = client.put(f"/api/segments/{segment['id']}", json={'waypoint_ids': [3, 1]})
    assert resp.status_code == 200
    assert resp.get_json()['waypoint_ids'] == [3, 1]


def test_list_circuits_includes_segments(client):
    # A tela de Circuitos precisa desenhar todos os circuitos no mapa de uma
    # vez -- sem segmentos aqui, sobraria só o nome, sem geometria pra traçar.
    circuit = client.post('/api/circuits', json={'name': 'POP Centro -> Cliente'}).get_json()
    client.post(f"/api/circuits/{circuit['id']}/segments", json={
        'order_index': 0, 'origin_point_id': 1, 'destination_point_id': 2, 'waypoint_ids': [3],
    })

    resp = client.get('/api/circuits')
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body) == 1
    assert len(body[0]['segments']) == 1
    assert body[0]['segments'][0]['origin_point_id'] == 1


def test_delete_circuit_cascades_segments(client):
    circuit = client.post('/api/circuits', json={'name': 'X'}).get_json()
    client.post(f"/api/circuits/{circuit['id']}/segments", json={
        'order_index': 0, 'origin_point_id': 1, 'destination_point_id': 2, 'waypoint_ids': [],
    })

    resp = client.delete(f"/api/circuits/{circuit['id']}")
    assert resp.status_code == 204

    resp = client.get('/api/circuits')
    assert resp.get_json() == []
