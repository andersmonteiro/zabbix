import time

import pytest

from alert_poller import AlertCache
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
        '60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'},
        '60010': {'lastvalue': '1', 'lastclock': '9999999999'}, '60011': {'lastvalue': '-19.4', 'lastclock': '9999999999'}, '60012': {'lastvalue': '0', 'lastclock': '9999999999'},
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
        '60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'},
        '60010': {'lastvalue': '1', 'lastclock': '9999999999'}, '60011': {'lastvalue': '-27.0', 'lastclock': '9999999999'}, '60012': {'lastvalue': '0', 'lastclock': '9999999999'},
    })

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    assert state['circuits'][0]['segments'][0]['status'] == 'warn'


def test_build_map_state_marks_everything_unknown_when_cache_stale(session):
    _seed_circuit(session)
    cache = StatusCache()
    cache.update({'60001': {'lastvalue': '1', 'lastclock': '9999999999'}})
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
    cache.update({'60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'},
                   '60010': {'lastvalue': '1', 'lastclock': '9999999999'}, '60011': {'lastvalue': '-19.4', 'lastclock': '9999999999'}, '60012': {'lastvalue': '0', 'lastclock': '9999999999'}})

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    wp = next(p for p in state['points'] if p['id'] == waypoint.id)
    assert wp['point_type'] == 'waypoint'
    assert 'status' not in wp


# --- Finding 7: the UI needs the age of the data to show "dados desde X" -----

def test_build_map_state_reports_last_refresh_age_when_fresh(session):
    _seed_circuit(session)
    cache = StatusCache()
    cache.update({'60001': {'lastvalue': '1', 'lastclock': '9999999999'}})

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    assert state['last_refresh_seconds_ago'] is not None
    assert 0 <= state['last_refresh_seconds_ago'] < 5


def test_build_map_state_reports_last_refresh_age_when_stale(session):
    _seed_circuit(session)
    cache = StatusCache()
    cache.update({'60001': {'lastvalue': '1', 'lastclock': '9999999999'}})
    cache._last_refresh = time.time() - 600

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    assert state['stale'] is True
    assert 595 <= state['last_refresh_seconds_ago'] <= 605


def test_build_map_state_last_refresh_age_is_none_when_never_refreshed(session):
    _seed_circuit(session)
    cache = StatusCache()  # never updated

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    assert state['stale'] is True
    assert state['last_refresh_seconds_ago'] is None


# --- snmp_offline: SNMP down but the link is still reachable by ping --------

def test_segment_reports_up_via_ping_when_snmp_is_offline(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    segment.zabbix_snmp_available_itemid = '60013'
    session.commit()
    cache = StatusCache()
    cache.update({
        '60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'},
        '60010': {'lastvalue': '1', 'lastclock': '9999999999'},  # operstatus driven by ping -- still up
        '60013': {'lastvalue': '0', 'lastclock': '9999999999'},  # SNMP itself is down
    })

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    seg = state['circuits'][0]['segments'][0]
    assert seg['status'] == 'up'
    assert seg['snmp_offline'] is True


def test_segment_snmp_offline_is_false_when_snmp_responds(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    segment.zabbix_snmp_available_itemid = '60013'
    session.commit()
    cache = StatusCache()
    cache.update({
        '60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'},
        '60010': {'lastvalue': '1', 'lastclock': '9999999999'}, '60013': {'lastvalue': '1', 'lastclock': '9999999999'},
    })

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    seg = state['circuits'][0]['segments'][0]
    assert seg['snmp_offline'] is False


def test_segment_snmp_offline_is_false_when_field_not_configured(session):
    _seed_circuit(session)  # no zabbix_snmp_available_itemid set
    cache = StatusCache()
    cache.update({'60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'}, '60010': {'lastvalue': '1', 'lastclock': '9999999999'}})

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    seg = state['circuits'][0]['segments'][0]
    assert seg['snmp_offline'] is False


def test_segment_snmp_offline_is_false_when_stale(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    segment.zabbix_snmp_available_itemid = '60013'
    session.commit()
    cache = StatusCache()  # never updated -> stale

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    seg = state['circuits'][0]['segments'][0]
    assert seg['snmp_offline'] is False


# --- throughput/speed: raw Zabbix items are bps, UI needs Mbps -------------

def test_throughput_and_speed_are_converted_from_bps_to_mbps(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    segment.zabbix_throughput_in_itemid = '60020'
    segment.zabbix_throughput_out_itemid = '60021'
    segment.zabbix_speed_itemid = '60022'
    session.commit()
    cache = StatusCache()
    cache.update({
        '60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'}, '60010': {'lastvalue': '1', 'lastclock': '9999999999'},
        '60020': {'lastvalue': '3491629016', 'lastclock': '9999999999'},  # ~3.49 Gbps raw bps
        '60021': {'lastvalue': '1529953112', 'lastclock': '9999999999'},
        '60022': {'lastvalue': '100000000000', 'lastclock': '9999999999'},  # 100 Gbps port speed
    })

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    seg = state['circuits'][0]['segments'][0]
    assert seg['throughput_in_mbps'] == pytest.approx(3491.629016)
    assert seg['throughput_out_mbps'] == pytest.approx(1529.953112)
    assert seg['speed_mbps'] == pytest.approx(100000.0)


# --- equipment Point: SNMP-offline flag, uptime, real Zabbix alerts --------

def test_point_reports_snmp_offline_independent_of_ping(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    origin.zabbix_snmp_available_itemid = '60030'
    session.commit()
    cache = StatusCache()
    cache.update({
        '60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'}, '60010': {'lastvalue': '1', 'lastclock': '9999999999'},
        '60030': {'lastvalue': '0', 'lastclock': '9999999999'},
    })

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    origin_point = next(p for p in state['points'] if p['id'] == origin.id)
    assert origin_point['status'] == 'up'
    assert origin_point['snmp_offline'] is True


def test_point_exposes_uptime_seconds(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    origin.zabbix_uptime_itemid = '60031'
    session.commit()
    cache = StatusCache()
    cache.update({
        '60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'}, '60010': {'lastvalue': '1', 'lastclock': '9999999999'},
        '60031': {'lastvalue': '864000', 'lastclock': '9999999999'},
    })

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    origin_point = next(p for p in state['points'] if p['id'] == origin.id)
    assert origin_point['uptime_seconds'] == 864000.0


def test_point_alert_severity_from_matching_open_problem(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    origin.zabbix_hostid = '10500'
    session.commit()
    cache = StatusCache()
    cache.update({'60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'}, '60010': {'lastvalue': '1', 'lastclock': '9999999999'}})
    alert_cache = AlertCache()
    alert_cache.update([
        {'eventid': '1', 'hostid': '10500', 'severity': 2, 'name': 'Atenção'},
        {'eventid': '2', 'hostid': '10500', 'severity': 4, 'name': 'Problema grave'},
        {'eventid': '3', 'hostid': '99999', 'severity': 5, 'name': 'outro host'},
    ])

    state = build_map_state(session, cache, stale_threshold_seconds=120, alert_cache=alert_cache)
    origin_point = next(p for p in state['points'] if p['id'] == origin.id)
    assert origin_point['alert_severity'] == 4  # worst of the two open problems on this host
    assert origin_point['alert_count'] == 2


def test_point_alert_severity_is_none_without_open_problems(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    origin.zabbix_hostid = '10500'
    session.commit()
    cache = StatusCache()
    cache.update({'60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'}, '60010': {'lastvalue': '1', 'lastclock': '9999999999'}})
    alert_cache = AlertCache()
    alert_cache.update([])

    state = build_map_state(session, cache, stale_threshold_seconds=120, alert_cache=alert_cache)
    origin_point = next(p for p in state['points'] if p['id'] == origin.id)
    assert origin_point['alert_severity'] is None
    assert origin_point['alert_count'] == 0


def test_point_alert_severity_is_none_when_no_alert_cache_wired(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    origin.zabbix_hostid = '10500'
    session.commit()
    cache = StatusCache()
    cache.update({'60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'}, '60010': {'lastvalue': '1', 'lastclock': '9999999999'}})

    state = build_map_state(session, cache, stale_threshold_seconds=120)  # no alert_cache passed
    origin_point = next(p for p in state['points'] if p['id'] == origin.id)
    assert origin_point['alert_severity'] is None
    assert origin_point['alert_count'] == 0


# --- Segment: origin/destination names, port name, optical TX -------------

def test_segment_includes_origin_and_destination_names(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    cache = StatusCache()
    cache.update({'60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'}, '60010': {'lastvalue': '1', 'lastclock': '9999999999'}})

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    seg = state['circuits'][0]['segments'][0]
    assert seg['origin_name'] == 'POP Centro'
    assert seg['destination_name'] == 'Cliente'


def test_segment_exposes_port_name_and_optical_tx(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    segment.port_name = '100GE0/0/1 - KM30-40G'
    segment.zabbix_optical_tx_itemid = '60040'
    session.commit()
    cache = StatusCache()
    cache.update({
        '60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'}, '60010': {'lastvalue': '1', 'lastclock': '9999999999'},
        '60040': {'lastvalue': '-3.2', 'lastclock': '9999999999'},
    })

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    seg = state['circuits'][0]['segments'][0]
    assert seg['port_name'] == '100GE0/0/1 - KM30-40G'
    assert seg['optical_tx_dbm'] == -3.2


# --- lastclock == '0' means Zabbix never actually collected the item -------
# (common for trapper items fed by an external script that hasn't run yet:
# item.get still returns lastvalue '0', which must not render as a real
# zero reading, e.g. "0 dBm" optical signal looking like a perfect link).

def test_never_collected_trapper_item_reads_as_no_data_not_zero(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    cache = StatusCache()
    cache.update({
        '60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'},
        '60010': {'lastvalue': '1', 'lastclock': '9999999999'},
        '60011': {'lastvalue': '0', 'lastclock': '0'},  # never collected
    })

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    seg = state['circuits'][0]['segments'][0]
    assert seg['optical_rx_dbm'] is None


# --- Point latency (RTT) and Segment utilization_pct ------------------------

def test_point_exposes_latency_in_milliseconds(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    origin.zabbix_latency_itemid = '60050'
    session.commit()
    cache = StatusCache()
    cache.update({
        '60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'},
        '60010': {'lastvalue': '1', 'lastclock': '9999999999'},
        '60050': {'lastvalue': '0.0123', 'lastclock': '9999999999'},  # icmppingsec, seconds
    })

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    origin_point = next(p for p in state['points'] if p['id'] == origin.id)
    assert origin_point['latency_ms'] == pytest.approx(12.3)


def test_point_latency_is_none_when_not_configured(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    cache = StatusCache()
    cache.update({'60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'}, '60010': {'lastvalue': '1', 'lastclock': '9999999999'}})

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    origin_point = next(p for p in state['points'] if p['id'] == origin.id)
    assert origin_point['latency_ms'] is None


def test_segment_utilization_pct_from_throughput_and_speed(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    segment.zabbix_throughput_in_itemid = '60060'
    segment.zabbix_throughput_out_itemid = '60061'
    segment.zabbix_speed_itemid = '60062'
    session.commit()
    cache = StatusCache()
    cache.update({
        '60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'}, '60010': {'lastvalue': '1', 'lastclock': '9999999999'},
        '60060': {'lastvalue': '40000000000', 'lastclock': '9999999999'},  # 40 Gbps in
        '60061': {'lastvalue': '10000000000', 'lastclock': '9999999999'},  # 10 Gbps out
        '60062': {'lastvalue': '100000000000', 'lastclock': '9999999999'},  # 100 Gbps port
    })

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    seg = state['circuits'][0]['segments'][0]
    assert seg['utilization_pct'] == pytest.approx(40.0)  # busiest direction (in) / speed


def test_segment_utilization_pct_is_capped_at_100(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    segment.zabbix_throughput_in_itemid = '60060'
    segment.zabbix_speed_itemid = '60062'
    session.commit()
    cache = StatusCache()
    cache.update({
        '60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'}, '60010': {'lastvalue': '1', 'lastclock': '9999999999'},
        '60060': {'lastvalue': '120000000000', 'lastclock': '9999999999'},  # over-reporting past nominal speed
        '60062': {'lastvalue': '100000000000', 'lastclock': '9999999999'},
    })

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    seg = state['circuits'][0]['segments'][0]
    assert seg['utilization_pct'] == 100.0


def test_segment_utilization_pct_is_none_without_speed_configured(session):
    origin, dest, waypoint, circuit, segment = _seed_circuit(session)
    segment.zabbix_throughput_in_itemid = '60060'
    session.commit()
    cache = StatusCache()
    cache.update({
        '60001': {'lastvalue': '1', 'lastclock': '9999999999'}, '60002': {'lastvalue': '1', 'lastclock': '9999999999'}, '60010': {'lastvalue': '1', 'lastclock': '9999999999'},
        '60060': {'lastvalue': '40000000000', 'lastclock': '9999999999'},
    })

    state = build_map_state(session, cache, stale_threshold_seconds=120)
    seg = state['circuits'][0]['segments'][0]
    assert seg['utilization_pct'] is None
