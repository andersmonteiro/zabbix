import time

from flask import Blueprint, jsonify

from models import Point, Circuit
from status import compute_status

map_state_bp = Blueprint('map_state', __name__, url_prefix='/api')

_session_factory = None
_cache = None
_stale_threshold_seconds = 120


def init_map_routes(session_factory, cache, stale_threshold_seconds=120):
    global _session_factory, _cache, _stale_threshold_seconds
    _session_factory = session_factory
    _cache = cache
    _stale_threshold_seconds = stale_threshold_seconds


def _lastvalue(cache, itemid, cast=str):
    if itemid is None:
        return None
    item = cache.get(itemid)
    if item is None:
        return None
    try:
        return cast(item['lastvalue'])
    except (TypeError, ValueError):
        return None


def _is_stale(cache, stale_threshold_seconds):
    last_refresh = cache.last_refresh()
    if last_refresh is None:
        return True
    return (time.time() - last_refresh) > stale_threshold_seconds


def build_map_state(session, cache, stale_threshold_seconds=120):
    stale = _is_stale(cache, stale_threshold_seconds)

    points_out = []
    for point in session.query(Point).all():
        entry = {
            'id': point.id, 'name': point.name, 'lat': point.lat, 'lng': point.lng,
            'point_type': point.point_type,
        }
        if point.point_type == 'equipment':
            operstatus = None if stale else _lastvalue(cache, point.zabbix_status_itemid, int)
            entry['status'] = compute_status(operstatus=operstatus)
            entry['equipment_model'] = point.equipment_model
            entry['equipment_ip'] = point.equipment_ip
            cpu = None if stale else _lastvalue(cache, point.zabbix_cpu_itemid, float)
            entry['cpu_percent'] = cpu
        points_out.append(entry)

    circuits_out = []
    for circuit in session.query(Circuit).all():
        segments_out = []
        for segment in sorted(circuit.segments, key=lambda s: s.order_index):
            operstatus = None if stale else _lastvalue(cache, segment.zabbix_operstatus_itemid, int)
            optical_rx = None if stale else _lastvalue(cache, segment.zabbix_optical_rx_itemid, float)
            error_count = None if stale else _lastvalue(cache, segment.zabbix_error_itemid, float)

            segments_out.append({
                'id': segment.id,
                'circuit_id': segment.circuit_id,
                'order_index': segment.order_index,
                'origin_point_id': segment.origin_point_id,
                'destination_point_id': segment.destination_point_id,
                'waypoint_ids': segment.waypoint_ids or [],
                'status': compute_status(
                    operstatus=operstatus, optical_rx_dbm=optical_rx,
                    signal_warn_threshold_dbm=segment.signal_warn_threshold_dbm,
                    error_count=error_count,
                ),
                'speed_mbps': None if stale else _lastvalue(cache, segment.zabbix_speed_itemid, float),
                'throughput_in_mbps': None if stale else _lastvalue(cache, segment.zabbix_throughput_in_itemid, float),
                'throughput_out_mbps': None if stale else _lastvalue(cache, segment.zabbix_throughput_out_itemid, float),
                'optical_rx_dbm': optical_rx,
                'error_count': error_count,
                'signal_warn_threshold_dbm': segment.signal_warn_threshold_dbm,
            })
        circuits_out.append({'id': circuit.id, 'name': circuit.name, 'segments': segments_out})

    return {'points': points_out, 'circuits': circuits_out, 'stale': stale}


@map_state_bp.route('/map-state', methods=['GET'])
def map_state():
    session = _session_factory()
    try:
        return jsonify(build_map_state(session, _cache, _stale_threshold_seconds))
    finally:
        session.close()
