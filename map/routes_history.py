import time

from flask import Blueprint, jsonify, request

from models import Segment
from zabbix_client import ZabbixAPIError

history_bp = Blueprint('history', __name__, url_prefix='/api')

_session_factory = None
_zabbix_client = None

MIN_HOURS = 1
MAX_HOURS = 168  # 7 dias -- history.get sem agregação fica pesado além disso


def init_history_routes(session_factory, zabbix_client):
    global _session_factory, _zabbix_client
    _session_factory = session_factory
    _zabbix_client = zabbix_client


def _fetch_series(itemid, time_from, time_till):
    """Zabbix's history.get needs the item's own value_type (0=float,
    3=unsigned int, ...) as the "history" param -- the throughput items
    here (ifHCIn/OutOctets, pre-processed to bps) come back as unsigned,
    not float, so this is looked up per item instead of assumed."""
    if itemid is None:
        return []
    item_info = _zabbix_client.call('item.get', {'itemids': [itemid], 'output': ['value_type']})
    if not item_info:
        return []
    value_type = int(item_info[0]['value_type'])
    raw = _zabbix_client.call('history.get', {
        'itemids': [itemid], 'history': value_type,
        'time_from': time_from, 'time_till': time_till,
        'output': 'extend', 'sortfield': 'clock', 'sortorder': 'ASC',
    })
    return [[int(p['clock']), float(p['value'])] for p in raw]


@history_bp.route('/segments/<int:segment_id>/history', methods=['GET'])
def segment_history(segment_id):
    hours = request.args.get('hours', default=6, type=int) or 6
    hours = max(MIN_HOURS, min(hours, MAX_HOURS))

    session = _session_factory()
    try:
        segment = session.get(Segment, segment_id)
        if segment is None:
            return jsonify({'error': 'Segmento não encontrado'}), 404

        time_till = int(time.time())
        time_from = time_till - hours * 3600

        try:
            in_series = _fetch_series(segment.zabbix_throughput_in_itemid, time_from, time_till)
            out_series = _fetch_series(segment.zabbix_throughput_out_itemid, time_from, time_till)
        except ZabbixAPIError as e:
            return jsonify({'error': str(e)}), 502

        # bps bruto -> Mbps, mesma conversão usada em build_map_state().
        return jsonify({
            'hours': hours,
            'throughput_in_mbps': [[ts, v / 1_000_000] for ts, v in in_series],
            'throughput_out_mbps': [[ts, v / 1_000_000] for ts, v in out_series],
        })
    finally:
        session.close()
