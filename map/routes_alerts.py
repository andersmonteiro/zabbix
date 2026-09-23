import time

from flask import Blueprint, jsonify

alerts_bp = Blueprint('alerts', __name__, url_prefix='/api')

_cache = None
_stale_threshold_seconds = 120


def init_alerts_routes(cache, stale_threshold_seconds=120):
    global _cache, _stale_threshold_seconds
    _cache = cache
    _stale_threshold_seconds = stale_threshold_seconds


def _is_stale():
    last_refresh = _cache.last_refresh()
    if last_refresh is None:
        return True
    return (time.time() - last_refresh) > _stale_threshold_seconds


def _last_refresh_seconds_ago():
    last_refresh = _cache.last_refresh()
    if last_refresh is None:
        return None
    return max(0, int(time.time() - last_refresh))


@alerts_bp.route('/alerts', methods=['GET'])
def list_alerts():
    stale = _is_stale()
    return jsonify({
        'problems': [] if stale else _cache.get_all(),
        'stale': stale,
        'last_refresh_seconds_ago': _last_refresh_seconds_ago(),
    })
