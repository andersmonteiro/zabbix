import time

from flask import Blueprint, jsonify

from models import Point, Circuit
from status import compute_status

map_state_bp = Blueprint('map_state', __name__, url_prefix='/api')

_session_factory = None
_cache = None
_alert_cache = None
_stale_threshold_seconds = 120


def init_map_routes(session_factory, cache, stale_threshold_seconds=120, alert_cache=None):
    global _session_factory, _cache, _stale_threshold_seconds, _alert_cache
    _session_factory = session_factory
    _cache = cache
    _stale_threshold_seconds = stale_threshold_seconds
    _alert_cache = alert_cache


def _lastvalue(cache, itemid, cast=str):
    if itemid is None:
        return None
    item = cache.get(itemid)
    if item is None:
        return None
    # lastclock == '0' means Zabbix has never actually collected this item
    # (common for trapper items fed by an external script that hasn't run
    # successfully yet) -- item.get still returns it with lastvalue '0',
    # which would otherwise render as a real zero reading (e.g. "0 dBm"
    # optical signal) instead of "no data".
    if item.get('lastclock', '0') == '0':
        return None
    try:
        return cast(item['lastvalue'])
    except (TypeError, ValueError):
        return None


def _bps_to_mbps(value):
    """Zabbix's ifHCInOctets/ifHCOutOctets items in these templates are
    pre-processed to bits/second (units: "bps"), not megabits -- dividing
    raw bytes-per-second-turned-bits here was missing entirely before, so
    the UI showed e.g. 3491629016 "Mbps" instead of 3491.63 Mbps."""
    if value is None:
        return None
    return value / 1_000_000


def _is_stale(cache, stale_threshold_seconds):
    last_refresh = cache.last_refresh()
    if last_refresh is None:
        return True
    return (time.time() - last_refresh) > stale_threshold_seconds


def _last_refresh_seconds_ago(cache):
    """Age of the cached Zabbix data in whole seconds, or None if the poller has
    never completed a refresh. The frontend needs this to tell the operator
    "Zabbix is down" apart from "nothing is configured yet"."""
    last_refresh = cache.last_refresh()
    if last_refresh is None:
        return None
    return max(0, int(time.time() - last_refresh))


def _worst_alert_by_hostid(alert_cache):
    """{hostid: {severity, count}} for the single worst OPEN problem per
    host. The cache now also holds recently-resolved problems (so the
    Alertas page can show a "Resolvidos" tab) -- those must never count here,
    or a host would keep glowing red on the map for hours after it recovered.
    None entries (host unresolved when the alert was polled) are skipped --
    they can't be matched to a Point anyway."""
    if alert_cache is None:
        return {}
    worst = {}
    for problem in alert_cache.get_all():
        if problem.get('resolved'):
            continue
        hostid = problem.get('hostid')
        if hostid is None:
            continue
        entry = worst.setdefault(hostid, {'severity': 0, 'count': 0})
        entry['count'] += 1
        entry['severity'] = max(entry['severity'], problem['severity'])
    return worst


def build_map_state(session, cache, stale_threshold_seconds=120, alert_cache=None):
    stale = _is_stale(cache, stale_threshold_seconds)
    last_refresh_seconds_ago = _last_refresh_seconds_ago(cache)
    alerts_by_hostid = _worst_alert_by_hostid(alert_cache)

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
            # Exposto pro frontend poder linkar direto pra /alertas.html?hostid=...
            # a partir do marcador/lista de hosts -- sem isso não dá pra filtrar
            # a página de alertas por host sem re-adivinhar o hostid lá.
            entry['zabbix_hostid'] = point.zabbix_hostid
            cpu = None if stale else _lastvalue(cache, point.zabbix_cpu_itemid, float)
            entry['cpu_percent'] = cpu

            snmp_available = None if stale else _lastvalue(cache, point.zabbix_snmp_available_itemid, int)
            entry['snmp_offline'] = (
                point.zabbix_snmp_available_itemid is not None and snmp_available == 0
            )
            entry['uptime_seconds'] = None if stale else _lastvalue(cache, point.zabbix_uptime_itemid, float)
            latency_seconds = None if stale else _lastvalue(cache, point.zabbix_latency_itemid, float)
            entry['latency_ms'] = None if latency_seconds is None else latency_seconds * 1000

            alert = alerts_by_hostid.get(point.zabbix_hostid)
            entry['alert_severity'] = alert['severity'] if alert else None
            entry['alert_count'] = alert['count'] if alert else 0
        points_out.append(entry)

    points_by_id = {p.id: p for p in session.query(Point).all()}

    circuits_out = []
    for circuit in session.query(Circuit).all():
        segments_out = []
        for segment in sorted(circuit.segments, key=lambda s: s.order_index):
            operstatus = None if stale else _lastvalue(cache, segment.zabbix_operstatus_itemid, int)
            optical_rx = None if stale else _lastvalue(cache, segment.zabbix_optical_rx_itemid, float)
            optical_tx = None if stale else _lastvalue(cache, segment.zabbix_optical_tx_itemid, float)
            error_count = None if stale else _lastvalue(cache, segment.zabbix_error_itemid, float)
            snmp_available = None if stale else _lastvalue(cache, segment.zabbix_snmp_available_itemid, int)
            # snmp_available is a separate signal from operstatus on purpose: a
            # segment can be genuinely up (ping/agent reachable) while SNMP
            # itself doesn't answer, in which case the line should still read
            # "up" but the operator needs a visible cue that the interface
            # detail (traffic, real port state) isn't trustworthy right now.
            snmp_offline = segment.zabbix_snmp_available_itemid is not None and snmp_available == 0

            origin = points_by_id.get(segment.origin_point_id)
            destination = points_by_id.get(segment.destination_point_id)

            throughput_in_raw = None if stale else _lastvalue(cache, segment.zabbix_throughput_in_itemid, float)
            throughput_out_raw = None if stale else _lastvalue(cache, segment.zabbix_throughput_out_itemid, float)
            speed_raw = None if stale else _lastvalue(cache, segment.zabbix_speed_itemid, float)

            throughput_in_mbps = _bps_to_mbps(throughput_in_raw)
            throughput_out_mbps = _bps_to_mbps(throughput_out_raw)
            speed_mbps = _bps_to_mbps(speed_raw)
            utilization_pct = None
            if speed_mbps and (throughput_in_mbps is not None or throughput_out_mbps is not None):
                busiest = max(throughput_in_mbps or 0, throughput_out_mbps or 0)
                utilization_pct = min(100.0, (busiest / speed_mbps) * 100)

            segments_out.append({
                'id': segment.id,
                'circuit_id': segment.circuit_id,
                'order_index': segment.order_index,
                'origin_point_id': segment.origin_point_id,
                'destination_point_id': segment.destination_point_id,
                'origin_name': origin.name if origin else None,
                'destination_name': destination.name if destination else None,
                'waypoint_ids': segment.waypoint_ids or [],
                'port_name': segment.port_name,
                'status': compute_status(
                    operstatus=operstatus, optical_rx_dbm=optical_rx,
                    signal_warn_threshold_dbm=segment.signal_warn_threshold_dbm,
                    error_count=error_count,
                ),
                # Zabbix's ifHCIn/OutOctets items here are pre-processed to
                # bits/second (units: "bps") -- /1e6 to get Mbps for display.
                'speed_mbps': speed_mbps,
                'throughput_in_mbps': throughput_in_mbps,
                'throughput_out_mbps': throughput_out_mbps,
                # % of the port's own nominal speed the busiest direction is
                # using right now -- only computable when speed_mbps is
                # configured, which most DTC/Datacom segments don't have yet.
                'utilization_pct': utilization_pct,
                'optical_rx_dbm': optical_rx,
                'optical_tx_dbm': optical_tx,
                'error_count': error_count,
                'signal_warn_threshold_dbm': segment.signal_warn_threshold_dbm,
                'snmp_offline': snmp_offline,
            })
        circuits_out.append({'id': circuit.id, 'name': circuit.name, 'segments': segments_out})

    return {
        'points': points_out,
        'circuits': circuits_out,
        'stale': stale,
        'last_refresh_seconds_ago': last_refresh_seconds_ago,
    }


@map_state_bp.route('/map-state', methods=['GET'])
def map_state():
    session = _session_factory()
    try:
        return jsonify(build_map_state(session, _cache, _stale_threshold_seconds, _alert_cache))
    finally:
        session.close()
