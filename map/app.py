import atexit
import os
import threading

from flask import Flask, jsonify
from werkzeug.security import generate_password_hash

from models import get_engine, get_session_factory, init_db, Point, Segment, User

app = Flask(__name__, static_folder='static', static_url_path='')
app.secret_key = os.environ.get('MAP_SECRET_KEY') or os.urandom(32)
app.config['PERMANENT_SESSION_LIFETIME'] = 60 * 60 * 24 * 7  # 7 dias

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

from auth import auth_bp, init_auth, register_auth_guard
from routes_users import users_bp, init_users_routes

init_auth(SessionLocal)
init_users_routes(SessionLocal)
app.register_blueprint(auth_bp)
app.register_blueprint(users_bp)
register_auth_guard(app)


def _seed_default_admin():
    """First boot has no users yet, so nobody could ever log in — seed one
    from env vars (mirrors the WEBHOOK_TOKEN / ZABBIX_PASS pattern install.sh
    already uses for other components)."""
    session = SessionLocal()
    try:
        if session.query(User).count() > 0:
            return
        username = os.environ.get('MAP_ADMIN_USER', 'admin')
        password = os.environ.get('MAP_ADMIN_PASSWORD')
        if not password:
            return
        session.add(User(username=username, password_hash=generate_password_hash(password)))
        session.commit()
    finally:
        session.close()


_seed_default_admin()

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
            itemids.update(filter(None, [
                point.zabbix_status_itemid, point.zabbix_cpu_itemid,
                point.zabbix_snmp_available_itemid, point.zabbix_uptime_itemid,
            ]))
        for segment in session.query(Segment):
            itemids.update(filter(None, [
                segment.zabbix_speed_itemid, segment.zabbix_throughput_in_itemid,
                segment.zabbix_throughput_out_itemid, segment.zabbix_optical_rx_itemid,
                segment.zabbix_optical_tx_itemid, segment.zabbix_error_itemid,
                segment.zabbix_operstatus_itemid, segment.zabbix_snmp_available_itemid,
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

from alert_poller import AlertCache, alert_poll_loop
from routes_alerts import alerts_bp, init_alerts_routes

ALERT_POLL_INTERVAL_SECONDS = int(os.environ.get('ALERT_POLL_INTERVAL_SECONDS', '30'))
alert_cache = AlertCache()
_alert_poller_stop_event = threading.Event()
_alert_poller_thread = threading.Thread(
    target=alert_poll_loop,
    args=(zabbix_client, alert_cache),
    kwargs={'interval_seconds': ALERT_POLL_INTERVAL_SECONDS, 'stop_event': _alert_poller_stop_event},
    daemon=True,
)
_alert_poller_thread.start()
atexit.register(_alert_poller_stop_event.set)

init_alerts_routes(alert_cache, STALE_THRESHOLD_SECONDS)
app.register_blueprint(alerts_bp)

# alert_cache feeds both the notification bell (above) and each equipment
# Point's alert_severity/alert_count on the map -- a real Zabbix problem
# open on that host, not just the raw ping/SNMP items.
init_map_routes(SessionLocal, status_cache, STALE_THRESHOLD_SECONDS, alert_cache=alert_cache)
app.register_blueprint(map_state_bp)

from routes_equipment_images import equipment_images_bp, init_equipment_images_routes

init_equipment_images_routes(os.environ.get('EQUIPMENT_IMAGES_DIR', '/app/equipment-images'))
app.register_blueprint(equipment_images_bp)

from routes_hosts import hosts_bp, init_hosts_routes

init_hosts_routes(zabbix_client)
app.register_blueprint(hosts_bp)


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


@app.route('/')
def index():
    return app.send_static_file('index.html')


@app.route('/api/config')
def config():
    return jsonify({
        'tile_provider': os.environ.get('TILE_PROVIDER', 'osm'),
        'mapbox_token': os.environ.get('MAPBOX_TOKEN', ''),
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=False)
