import pytest
from flask import Flask

from models import Base, get_engine, get_session_factory
from routes_points import points_bp, init_points_routes


@pytest.fixture
def client():
    engine = get_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)

    app = Flask(__name__)
    init_points_routes(session_factory)
    app.register_blueprint(points_bp)
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


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
