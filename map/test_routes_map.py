import time

import pytest

from models import Base, Point, Circuit, Segment, get_engine, get_session_factory
from poller import StatusCache
from routes_map import build_map_state


@pytest.fixture
def session():
    engine = get_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    yield session
    session.close()


def _seed_circuit(session):
    origin = Point(name='POP Centro', lat=-23.56, lng=-46.65, point_type='equipment',
                    zabbix_status_itemid='60001')
    dest = Point(name='Cliente', lat=-23.55, lng=-46.64, point_type='equipment',
                 zabbix_status_itemid='60002')
    waypoint = Point(name='Poste 12', lat=-23.559, lng=-46.649, point_type='waypoint')
    session.add_all([origin, dest, waypoint])
    session.commit()

    circuit = Circuit(name='POP Centro -> Cliente')
    session.add(circuit)
    session.commit()

    segment = Segment(
        circuit_id=circuit.id, order_index=0,
        origin_point_id=origin.id, destination_point_id=dest.id,
        waypoint_ids=[waypoint.id],
        zabbix_operstatus_itemid='60010', zabbix_optical_rx_itemid='60011',
        zabbix_error_itemid='60012', signal_warn_threshold_dbm=-25.0,
    )
    session.add(segment)
    session.commit()
    return origin, dest, waypoint, circuit, segment


def test_build_map_state_reports_up_when_cache_fresh_and_healthy(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    cache = StatusCache()
    cache.update({
        '60001': {'lastvalue': '1'}, '60002': {'lastvalue': '1'},
        '60010': {'lastvalue': '1'}, '60011': {'lastvalue': '-19.4'}, '60012': {'lastvalue': '0'},
    })

    state = build_map_state(session, cache, stale_threshold_seconds=120)

    assert state['stale'] is False
    origin_point = next(p for p in state['points'] if p['id'] == origin.id)
    assert origin_point['status'] == 'up'
    seg = state['circuits'][0]['segments'][0]
    assert seg['status'] == 'up'
    assert seg['optical_rx_dbm'] == -19.4


def test_build_map_state_marks_segment_warn_below_threshold(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    cache = StatusCache()
    cache.update({
        '60001': {'lastvalue': '1'}, '60002': {'lastvalue': '1'},
        '60010': {'lastvalue': '1'}, '60011': {'lastvalue': '-27.0'}, '60012': {'lastvalue': '0'},
    })

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    assert state['circuits'][0]['segments'][0]['status'] == 'warn'


def test_build_map_state_marks_everything_unknown_when_cache_stale(session):
    _seed_circuit(session)
    cache = StatusCache()
    cache.update({'60001': {'lastvalue': '1'}})
    # Force staleness: pretend the cache was last refreshed long ago
    cache._last_refresh = time.time() - 999

    state = build_map_state(session, cache, stale_threshold_seconds=120)

    assert state['stale'] is True
    # Waypoints never carry a 'status' field (see
    # test_build_map_state_waypoints_have_no_status_field); only assert on
    # points that do (equipment points).
    assert all(p.get('status', 'unknown') == 'unknown' for p in state['points'])
    assert all(s['status'] == 'unknown' for c in state['circuits'] for s in c['segments'])


def test_build_map_state_unknown_when_never_refreshed(session):
    _seed_circuit(session)
    cache = StatusCache()  # never updated

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    assert state['stale'] is True


def test_build_map_state_waypoints_have_no_status_field(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    cache = StatusCache()
    cache.update({'60001': {'lastvalue': '1'}, '60002': {'lastvalue': '1'},
                   '60010': {'lastvalue': '1'}, '60011': {'lastvalue': '-19.4'}, '60012': {'lastvalue': '0'}})

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    wp = next(p for p in state['points'] if p['id'] == waypoint.id)
    assert wp['point_type'] == 'waypoint'
    assert 'status' not in wp
