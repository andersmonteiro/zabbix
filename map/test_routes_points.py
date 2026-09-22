import pytest
from flask import Flask

from models import Base, Circuit, Segment, get_engine, get_session_factory
from routes_points import points_bp, init_points_routes


@pytest.fixture
def client_and_sessions():
    engine = get_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)

    app = Flask(__name__)
    init_points_routes(session_factory)
    app.register_blueprint(points_bp)
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c, session_factory


@pytest.fixture
def client(client_and_sessions):
    return client_and_sessions[0]


def test_list_points_empty(client):
    resp = client.get('/api/points')
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_create_and_list_point(client):
    resp = client.post('/api/points', json={
        'name': 'POP Centro', 'lat': -23.5605, 'lng': -46.6580,
        'point_type': 'equipment', 'zabbix_hostid': '10084',
        'zabbix_status_itemid': '55001', 'equipment_model': 'Huawei MA5800-X2',
        'equipment_ip': '10.20.1.1',
    })
    assert resp.status_code == 201
    created = resp.get_json()
    assert created['id'] is not None
    assert created['name'] == 'POP Centro'

    resp = client.get('/api/points')
    assert len(resp.get_json()) == 1


def test_create_point_rejects_missing_required_fields(client):
    resp = client.post('/api/points', json={'name': 'Sem coordenada'})
    assert resp.status_code == 400


def test_create_waypoint_without_zabbix_fields(client):
    resp = client.post('/api/points', json={
        'name': 'Poste 12', 'lat': -23.559, 'lng': -46.650, 'point_type': 'waypoint',
    })
    assert resp.status_code == 201
    assert resp.get_json()['zabbix_hostid'] is None


def test_update_point(client):
    created = client.post('/api/points', json={
        'name': 'Poste 12', 'lat': -23.559, 'lng': -46.650, 'point_type': 'waypoint',
    }).get_json()

    resp = client.put(f"/api/points/{created['id']}", json={'lat': -23.560, 'lng': -46.651})
    assert resp.status_code == 200
    assert resp.get_json()['lat'] == -23.560


def test_update_missing_point_returns_404(client):
    resp = client.put('/api/points/9999', json={'lat': 0, 'lng': 0})
    assert resp.status_code == 404


def test_delete_point(client):
    created = client.post('/api/points', json={
        'name': 'Poste 12', 'lat': -23.559, 'lng': -46.650, 'point_type': 'waypoint',
    }).get_json()

    resp = client.delete(f"/api/points/{created['id']}")
    assert resp.status_code == 204

    resp = client.get('/api/points')
    assert resp.get_json() == []


def _seed_segment(session_factory, origin_id, destination_id, waypoint_ids):
    session = session_factory()
    try:
        circuit = Circuit(name='Circuito de teste')
        session.add(circuit)
        session.commit()
        session.add(Segment(
            circuit_id=circuit.id, order_index=0,
            origin_point_id=origin_id, destination_point_id=destination_id,
            waypoint_ids=waypoint_ids,
        ))
        session.commit()
    finally:
        session.close()


def _create_point(client, name, point_type='equipment'):
    return client.post('/api/points', json={
        'name': name, 'lat': -23.55, 'lng': -46.64, 'point_type': point_type,
    }).get_json()


# --- Finding 5: deleting a referenced point must not dangle the FK -----------
# SQLite does not enforce foreign keys by default, so a bare DELETE looks fine
# here while corrupting data; on the production Postgres DDL the same delete
# raises IntegrityError -> unhandled 500. Guard it in the route instead.

def test_delete_point_referenced_as_segment_origin_returns_409(client_and_sessions):
    client, session_factory = client_and_sessions
    origin = _create_point(client, 'POP Centro')
    dest = _create_point(client, 'Cliente')
    _seed_segment(session_factory, origin['id'], dest['id'], [])

    resp = client.delete(f"/api/points/{origin['id']}")
    assert resp.status_code == 409
    assert 'segmento' in resp.get_json()['error'].lower()

    ids = [p['id'] for p in client.get('/api/points').get_json()]
    assert origin['id'] in ids


def test_delete_point_referenced_as_segment_destination_returns_409(client_and_sessions):
    client, session_factory = client_and_sessions
    origin = _create_point(client, 'POP Centro')
    dest = _create_point(client, 'Cliente')
    _seed_segment(session_factory, origin['id'], dest['id'], [])

    resp = client.delete(f"/api/points/{dest['id']}")
    assert resp.status_code == 409
    assert dest['id'] in [p['id'] for p in client.get('/api/points').get_json()]


def test_delete_waypoint_referenced_in_waypoint_ids_returns_409(client_and_sessions):
    client, session_factory = client_and_sessions
    origin = _create_point(client, 'POP Centro')
    dest = _create_point(client, 'Cliente')
    waypoint = _create_point(client, 'Poste 12', point_type='waypoint')
    _seed_segment(session_factory, origin['id'], dest['id'], [waypoint['id']])

    resp = client.delete(f"/api/points/{waypoint['id']}")
    assert resp.status_code == 409
    assert waypoint['id'] in [p['id'] for p in client.get('/api/points').get_json()]


def test_delete_unreferenced_point_still_works(client_and_sessions):
    client, session_factory = client_and_sessions
    origin = _create_point(client, 'POP Centro')
    dest = _create_point(client, 'Cliente')
    orphan = _create_point(client, 'Poste solto', point_type='waypoint')
    _seed_segment(session_factory, origin['id'], dest['id'], [])

    assert client.delete(f"/api/points/{orphan['id']}").status_code == 204


# --- Finding 6: lat/lng must be validated, not blow up as a 500 --------------

@pytest.mark.parametrize('lat,lng', [
    (None, -46.64),
    (-23.55, None),
    ('abc', -46.64),
    (-23.55, 'abc'),
    (91.0, -46.64),
    (-91.0, -46.64),
    (-23.55, 181.0),
    (-23.55, -181.0),
    (True, -46.64),
])
def test_create_point_rejects_invalid_coordinates(client, lat, lng):
    resp = client.post('/api/points', json={
        'name': 'Ruim', 'lat': lat, 'lng': lng, 'point_type': 'waypoint',
    })
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


def test_create_point_accepts_numeric_string_coordinates(client):
    resp = client.post('/api/points', json={
        'name': 'Via string', 'lat': '-23.55', 'lng': '-46.64', 'point_type': 'waypoint',
    })
    assert resp.status_code == 201
    assert resp.get_json()['lat'] == -23.55


def test_update_point_rejects_invalid_coordinates(client):
    created = _create_point(client, 'Poste 12', point_type='waypoint')

    resp = client.put(f"/api/points/{created['id']}", json={'lat': None})
    assert resp.status_code == 400

    resp = client.put(f"/api/points/{created['id']}", json={'lng': 999})
    assert resp.status_code == 400

    # Unchanged on disk
    assert client.get('/api/points').get_json()[0]['lat'] == -23.55
