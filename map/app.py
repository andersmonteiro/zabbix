import atexit
import os
import threading

from flask import Flask, jsonify

from models import get_engine, get_session_factory, init_db, Point, Segment

app = Flask(__name__)

DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql+psycopg2://{user}:{password}@postgres:5432/{db}'.format(
        user=os.environ.get('POSTGRES_USER', 'zabbix'),
        password=os.environ.get('POSTGRES_PASSWORD', ''),
        db=os.environ.get('POSTGRES_DB', 'zabbix'),
    ),
)

engine = get_engine(DATABASE_URL)
SessionLocal = get_session_factory(engine)
init_db(engine)

from routes_points import points_bp, init_points_routes
from routes_circuits import circuits_bp, init_circuits_routes
from routes_map import map_state_bp, init_map_routes
from poller import StatusCache, poll_loop
from zabbix_client import ZabbixClient

init_points_routes(SessionLocal)
app.register_blueprint(points_bp)

init_circuits_routes(SessionLocal)
app.register_blueprint(circuits_bp)

POLL_INTERVAL_SECONDS = int(os.environ.get('POLL_INTERVAL_SECONDS', '30'))
STALE_THRESHOLD_SECONDS = int(os.environ.get('STALE_THRESHOLD_SECONDS', '120'))

zabbix_client = ZabbixClient(
    url=os.environ.get('ZABBIX_URL', 'http://zabbix-frontend:8080'),
    user=os.environ.get('ZABBIX_USER', 'Admin'),
    password=os.environ.get('ZABBIX_PASS', ''),
    insecure=os.environ.get('ZABBIX_INSECURE', '0') == '1',
)
status_cache = StatusCache()


def _collect_itemids():
    session = SessionLocal()
    try:
        itemids = set()
        for point in session.query(Point).filter(Point.point_type == 'equipment'):
            itemids.update(filter(None, [point.zabbix_status_itemid, point.zabbix_cpu_itemid]))
        for segment in session.query(Segment):
            itemids.update(filter(None, [
                segment.zabbix_speed_itemid, segment.zabbix_throughput_in_itemid,
                segment.zabbix_throughput_out_itemid, segment.zabbix_optical_rx_itemid,
                segment.zabbix_error_itemid, segment.zabbix_operstatus_itemid,
            ]))
        return list(itemids)
    finally:
        session.close()


_poller_stop_event = threading.Event()
_poller_thread = threading.Thread(
    target=poll_loop,
    args=(zabbix_client, _collect_itemids, status_cache),
    kwargs={'interval_seconds': POLL_INTERVAL_SECONDS, 'stop_event': _poller_stop_event},
    daemon=True,
)
_poller_thread.start()
atexit.register(_poller_stop_event.set)

init_map_routes(SessionLocal, status_cache, STALE_THRESHOLD_SECONDS)
app.register_blueprint(map_state_bp)


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=False)
