import os

from flask import Flask, jsonify

from models import get_engine, get_session_factory, init_db

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

init_points_routes(SessionLocal)
app.register_blueprint(points_bp)

init_circuits_routes(SessionLocal)
app.register_blueprint(circuits_bp)


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=False)
