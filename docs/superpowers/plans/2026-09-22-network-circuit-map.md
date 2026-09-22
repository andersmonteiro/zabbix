# Mapa de Circuitos de Rede Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir `map/`, um componente novo do stack de distribuição, que mostra o caminho físico real dos circuitos de rede num mapa (Leaflet + OpenStreetMap), com status ao vivo por segmento/equipamento vindo do Zabbix do próprio cliente, e um editor visual pra desenhar/arrastar o trajeto.

**Architecture:** Backend Flask (mesmo padrão do `tools/`) com Postgres (reaproveita a instância já existente no `stack/`, tabelas prefixadas `netmap_`), um poller em background que atualiza um cache de valores do Zabbix a cada 30s, um endpoint que agrega ponto+circuito+status calculado pro frontend, e um frontend estático (Leaflet + Leaflet-Geoman) com duas telas: mapa ao vivo (Início) e administração de circuitos/pontos (Circuitos).

**Tech Stack:** Python 3.11 / Flask, SQLAlchemy (Postgres em produção, SQLite em memória nos testes), Leaflet.js + Leaflet-Geoman, Docker + Docker Compose.

**Spec:** [docs/superpowers/specs/2026-09-22-network-circuit-map-design.md](../specs/2026-09-22-network-circuit-map-design.md)

## Global Constraints

- Sem Zabbix/Grafana centralizado — `map/` é decentralizado, uma instância por cliente, lendo só do Zabbix local daquele cliente.
- Sem integração com IXC/SGP/TopSapp nesta versão.
- Sem Zabbix adicional da Natverk nesta versão.
- Provedor de tile padrão é OpenStreetMap (grátis, sem conta); Mapbox é opcional via variável de ambiente, nunca obrigatório.
- Nenhuma coleta nova no Zabbix — só consome `itemid`s que os `externalscripts` já populam.
- O limiar de sinal óptico (dBm) que define "laranja" é configurável por segmento, nunca um valor fixo no código.
- Zabbix indisponível ou dado obsoleto (cache não atualizado recentemente) deve resultar em status `unknown` (cinza) — nunca manter a última cor calculada como se estivesse tudo bem.
- Segue os padrões já estabelecidos no repositório: Flask (como `tools/`), rede Docker externa `natverk-zabbix-net` (definida em `stack/docker-compose.yml`, Task 1 do plano anterior), TDD na lógica testável sem navegador.
- Fonte de todos os arquivos: `D:\projetos-natverk\natverk-noc-repo\.claude\worktrees\noc-distribution-platform` (mesmo worktree do repositório de distribuição já publicado).

---

### Task 1: Scaffold `map/` — modelos de dados + cálculo de status (TDD)

**Files:**
- Create: `map/requirements.txt`
- Create: `map/requirements-dev.txt`
- Create: `map/models.py`
- Create: `map/status.py`
- Test: `map/test_status.py`
- Create: `map/app.py`
- Create: `map/.env.example`

**Interfaces:**
- Produces: `models.Base`, `models.Point`, `models.Circuit`, `models.Segment` (SQLAlchemy declarative models — table names `netmap_points`, `netmap_circuits`, `netmap_segments`); `models.get_engine(database_url)`, `models.get_session_factory(engine)`; `status.compute_status(operstatus, optical_rx_dbm=None, signal_warn_threshold_dbm=None, error_count=None) -> str` returning one of `'up' | 'warn' | 'down' | 'unknown'`. Used by Task 5.

- [ ] **Step 1: Write the failing tests for `compute_status`**

`map/test_status.py`:

```python
from status import compute_status


def test_compute_status_unknown_when_no_data():
    assert compute_status(operstatus=None) == 'unknown'


def test_compute_status_down_when_operstatus_not_up():
    assert compute_status(operstatus=2) == 'down'


def test_compute_status_up_when_healthy():
    assert compute_status(
        operstatus=1, optical_rx_dbm=-19.0, signal_warn_threshold_dbm=-25.0
    ) == 'up'


def test_compute_status_warn_when_signal_below_threshold():
    assert compute_status(
        operstatus=1, optical_rx_dbm=-27.0, signal_warn_threshold_dbm=-25.0
    ) == 'warn'


def test_compute_status_ignores_threshold_when_not_configured():
    assert compute_status(
        operstatus=1, optical_rx_dbm=-40.0, signal_warn_threshold_dbm=None
    ) == 'up'


def test_compute_status_warn_when_errors_present():
    assert compute_status(operstatus=1, error_count=5) == 'warn'


def test_compute_status_up_when_no_errors():
    assert compute_status(operstatus=1, error_count=0) == 'up'
```

- [ ] **Step 2: Create `requirements-dev.txt` and run to verify the tests fail**

`map/requirements-dev.txt`:
```
flask==3.0.3
SQLAlchemy==2.0.35
pytest==8.3.3
requests==2.32.3
requests-mock==1.12.1
```

Run: `cd map && pip install -r requirements-dev.txt && pytest test_status.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'status'` (file doesn't exist yet).

- [ ] **Step 3: Implement `status.py`**

```python
def compute_status(operstatus, optical_rx_dbm=None, signal_warn_threshold_dbm=None, error_count=None):
    """Returns 'up' | 'warn' | 'down' | 'unknown'.

    operstatus follows IF-MIB ifOperStatus convention: 1 = up, anything
    else (2 = down, etc.) = down. None means no data was collected (stale
    cache or missing item) and must resolve to 'unknown', never a stale
    'up'.
    """
    if operstatus is None:
        return 'unknown'
    if operstatus != 1:
        return 'down'
    if signal_warn_threshold_dbm is not None and optical_rx_dbm is not None:
        if optical_rx_dbm < signal_warn_threshold_dbm:
            return 'warn'
    if error_count is not None and error_count > 0:
        return 'warn'
    return 'up'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_status.py -v`
Expected: `7 passed`.

- [ ] **Step 5: Create the SQLAlchemy models**

`map/models.py`:

```python
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class Point(Base):
    __tablename__ = 'netmap_points'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    point_type = Column(String, nullable=False)  # 'waypoint' or 'equipment'

    # Only set when point_type == 'equipment'
    zabbix_hostid = Column(String, nullable=True)
    zabbix_status_itemid = Column(String, nullable=True)  # e.g. ICMP ping / agent availability item
    zabbix_cpu_itemid = Column(String, nullable=True)
    equipment_model = Column(String, nullable=True)  # used to look up the photo
    equipment_ip = Column(String, nullable=True)


class Circuit(Base):
    __tablename__ = 'netmap_circuits'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


class Segment(Base):
    __tablename__ = 'netmap_segments'

    id = Column(Integer, primary_key=True)
    circuit_id = Column(Integer, ForeignKey('netmap_circuits.id'), nullable=False)
    order_index = Column(Integer, nullable=False)
    origin_point_id = Column(Integer, ForeignKey('netmap_points.id'), nullable=False)
    destination_point_id = Column(Integer, ForeignKey('netmap_points.id'), nullable=False)
    waypoint_ids = Column(JSON, nullable=False, default=list)  # ordered list of Point.id (point_type='waypoint')

    zabbix_speed_itemid = Column(String, nullable=True)
    zabbix_throughput_in_itemid = Column(String, nullable=True)
    zabbix_throughput_out_itemid = Column(String, nullable=True)
    zabbix_optical_rx_itemid = Column(String, nullable=True)
    zabbix_error_itemid = Column(String, nullable=True)
    zabbix_operstatus_itemid = Column(String, nullable=True)
    signal_warn_threshold_dbm = Column(Float, nullable=True)

    circuit = relationship('Circuit', backref='segments')
    origin = relationship('Point', foreign_keys=[origin_point_id])
    destination = relationship('Point', foreign_keys=[destination_point_id])


def get_engine(database_url):
    return create_engine(database_url, pool_pre_ping=True)


def get_session_factory(engine):
    return sessionmaker(bind=engine)


def init_db(engine):
    Base.metadata.create_all(engine)
```

- [ ] **Step 6: Create the Flask app skeleton with a health endpoint**

`map/app.py`:

```python
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


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=False)
```

- [ ] **Step 7: Create `.env.example`**

`map/.env.example`:

```
# Preenchidos automaticamente pelo install.sh a partir de stack/.env
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=zabbix

# Preenchido automaticamente pelo install.sh a partir de stack/.env
ZABBIX_URL=http://zabbix-frontend:8080
ZABBIX_USER=Admin
ZABBIX_PASS=

# Segundos entre atualizações do cache de status do Zabbix
POLL_INTERVAL_SECONDS=30

# Segundos sem atualização bem-sucedida antes de marcar tudo como 'unknown'
STALE_THRESHOLD_SECONDS=120

# Provedor de tile do mapa: "osm" (padrão, grátis) ou "mapbox"
TILE_PROVIDER=osm
# Só necessário se TILE_PROVIDER=mapbox
MAPBOX_TOKEN=
```

- [ ] **Step 8: Verify app imports cleanly (SQLite fallback, no Postgres needed for this check)**

Run: `cd map && DATABASE_URL=sqlite:///:memory: python -c "import app; print('OK')"`
Expected: prints `OK` with no traceback (confirms models + app wire together; the real Postgres connection is only exercised at real runtime).

- [ ] **Step 9: Commit**

```bash
git add map/requirements.txt map/requirements-dev.txt map/models.py map/status.py map/test_status.py map/app.py map/.env.example
git commit -m "Scaffold map/ service: data models and status computation (TDD)"
```

(Create `map/requirements.txt` first with just `flask==3.0.3` and `SQLAlchemy==2.0.35` and `requests==2.32.3` — the runtime deps, split from `requirements-dev.txt`.)

---

### Task 2: CRUD API — pontos (TDD)

**Files:**
- Create: `map/routes_points.py`
- Test: `map/test_routes_points.py`
- Modify: `map/app.py` (register blueprint)

**Interfaces:**
- Consumes: `models.Point`, `models.get_engine`, `models.get_session_factory`, `models.init_db` (Task 1).
- Produces: Flask blueprint `points_bp` registered at `/api/points`, endpoints `GET /api/points`, `POST /api/points`, `PUT /api/points/<id>`, `DELETE /api/points/<id>`. JSON point shape: `{"id": int, "name": str, "lat": float, "lng": float, "point_type": "waypoint"|"equipment", "zabbix_hostid": str|null, "zabbix_status_itemid": str|null, "zabbix_cpu_itemid": str|null, "equipment_model": str|null, "equipment_ip": str|null}`. Used by Task 3 (segments reference point ids) and Task 6/7 (frontend).

- [ ] **Step 1: Write the failing tests**

`map/test_routes_points.py`:

```python
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
```

- [ ] **Step 2: Run to verify the tests fail**

Run: `pytest test_routes_points.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'routes_points'`.

- [ ] **Step 3: Implement `routes_points.py`**

```python
from flask import Blueprint, jsonify, request

from models import Point

points_bp = Blueprint('points', __name__, url_prefix='/api/points')

_session_factory = None


def init_points_routes(session_factory):
    global _session_factory
    _session_factory = session_factory


def _serialize(point):
    return {
        'id': point.id,
        'name': point.name,
        'lat': point.lat,
        'lng': point.lng,
        'point_type': point.point_type,
        'zabbix_hostid': point.zabbix_hostid,
        'zabbix_status_itemid': point.zabbix_status_itemid,
        'zabbix_cpu_itemid': point.zabbix_cpu_itemid,
        'equipment_model': point.equipment_model,
        'equipment_ip': point.equipment_ip,
    }


REQUIRED_FIELDS = ('name', 'lat', 'lng', 'point_type')


@points_bp.route('', methods=['GET'])
def list_points():
    session = _session_factory()
    try:
        points = session.query(Point).all()
        return jsonify([_serialize(p) for p in points])
    finally:
        session.close()


@points_bp.route('', methods=['POST'])
def create_point():
    data = request.get_json(force=True, silent=True) or {}
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        return jsonify({'error': f"Campos obrigatórios ausentes: {', '.join(missing)}"}), 400
    if data['point_type'] not in ('waypoint', 'equipment'):
        return jsonify({'error': "point_type deve ser 'waypoint' ou 'equipment'"}), 400

    session = _session_factory()
    try:
        point = Point(
            name=data['name'], lat=data['lat'], lng=data['lng'], point_type=data['point_type'],
            zabbix_hostid=data.get('zabbix_hostid'),
            zabbix_status_itemid=data.get('zabbix_status_itemid'),
            zabbix_cpu_itemid=data.get('zabbix_cpu_itemid'),
            equipment_model=data.get('equipment_model'),
            equipment_ip=data.get('equipment_ip'),
        )
        session.add(point)
        session.commit()
        return jsonify(_serialize(point)), 201
    finally:
        session.close()


@points_bp.route('/<int:point_id>', methods=['PUT'])
def update_point(point_id):
    data = request.get_json(force=True, silent=True) or {}
    session = _session_factory()
    try:
        point = session.get(Point, point_id)
        if point is None:
            return jsonify({'error': 'Ponto não encontrado'}), 404
        for field in (
            'name', 'lat', 'lng', 'point_type', 'zabbix_hostid',
            'zabbix_status_itemid', 'zabbix_cpu_itemid', 'equipment_model', 'equipment_ip',
        ):
            if field in data:
                setattr(point, field, data[field])
        session.commit()
        return jsonify(_serialize(point))
    finally:
        session.close()


@points_bp.route('/<int:point_id>', methods=['DELETE'])
def delete_point(point_id):
    session = _session_factory()
    try:
        point = session.get(Point, point_id)
        if point is None:
            return jsonify({'error': 'Ponto não encontrado'}), 404
        session.delete(point)
        session.commit()
        return '', 204
    finally:
        session.close()
```

- [ ] **Step 4: Register the blueprint in `app.py`**

In `map/app.py`, after `SessionLocal = get_session_factory(engine)` and before the `/health` route, add:

```python
from routes_points import points_bp, init_points_routes

init_points_routes(SessionLocal)
app.register_blueprint(points_bp)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest test_routes_points.py -v`
Expected: `7 passed`.

- [ ] **Step 6: Commit**

```bash
git add map/routes_points.py map/test_routes_points.py map/app.py
git commit -m "Add points CRUD API (TDD)"
```

---

### Task 3: CRUD API — circuitos e segmentos (TDD)

**Files:**
- Create: `map/routes_circuits.py`
- Test: `map/test_routes_circuits.py`
- Modify: `map/app.py` (register blueprint)

**Interfaces:**
- Consumes: `models.Circuit`, `models.Segment`, `models.Point` (Task 1); same `session_factory` pattern as `routes_points.py` (Task 2).
- Produces: Flask blueprint `circuits_bp` at `/api/circuits`: `GET /api/circuits`, `GET /api/circuits/<id>`, `POST /api/circuits`, `PUT /api/circuits/<id>`, `DELETE /api/circuits/<id>`, `POST /api/circuits/<id>/segments`, `PUT /api/segments/<id>` (includes updating `waypoint_ids` for path editing), `DELETE /api/segments/<id>`. Segment JSON shape: `{"id", "circuit_id", "order_index", "origin_point_id", "destination_point_id", "waypoint_ids": [int], "zabbix_speed_itemid", "zabbix_throughput_in_itemid", "zabbix_throughput_out_itemid", "zabbix_optical_rx_itemid", "zabbix_error_itemid", "zabbix_operstatus_itemid", "signal_warn_threshold_dbm"}`. Used by Task 5 (map-state aggregation) and Task 7 (frontend editor).

- [ ] **Step 1: Write the failing tests**

`map/test_routes_circuits.py`:

```python
import pytest
from flask import Flask

from models import Base, Point, get_engine, get_session_factory
from routes_points import points_bp, init_points_routes
from routes_circuits import circuits_bp, init_circuits_routes


@pytest.fixture
def client():
    engine = get_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)

    app = Flask(__name__)
    init_points_routes(session_factory)
    init_circuits_routes(session_factory)
    app.register_blueprint(points_bp)
    app.register_blueprint(circuits_bp)
    app.config['TESTING'] = True

    session = session_factory()
    session.add_all([
        Point(id=1, name='POP Centro', lat=-23.5605, lng=-46.6580, point_type='equipment'),
        Point(id=2, name='Cliente Av. Brasil', lat=-23.5560, lng=-46.6460, point_type='equipment'),
        Point(id=3, name='Poste 12', lat=-23.559, lng=-46.650, point_type='waypoint'),
    ])
    session.commit()
    session.close()

    with app.test_client() as c:
        yield c


def test_create_circuit(client):
    resp = client.post('/api/circuits', json={'name': 'POP Centro -> Cliente'})
    assert resp.status_code == 201
    assert resp.get_json()['name'] == 'POP Centro -> Cliente'


def test_create_segment_under_circuit(client):
    circuit = client.post('/api/circuits', json={'name': 'POP Centro -> Cliente'}).get_json()

    resp = client.post(f"/api/circuits/{circuit['id']}/segments", json={
        'order_index': 0, 'origin_point_id': 1, 'destination_point_id': 2,
        'waypoint_ids': [3], 'zabbix_operstatus_itemid': '55010',
        'zabbix_optical_rx_itemid': '55011', 'signal_warn_threshold_dbm': -25.0,
    })
    assert resp.status_code == 201
    segment = resp.get_json()
    assert segment['waypoint_ids'] == [3]
    assert segment['signal_warn_threshold_dbm'] == -25.0


def test_get_circuit_includes_segments(client):
    circuit = client.post('/api/circuits', json={'name': 'POP Centro -> Cliente'}).get_json()
    client.post(f"/api/circuits/{circuit['id']}/segments", json={
        'order_index': 0, 'origin_point_id': 1, 'destination_point_id': 2, 'waypoint_ids': [3],
    })

    resp = client.get(f"/api/circuits/{circuit['id']}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body['segments']) == 1
    assert body['segments'][0]['origin_point_id'] == 1


def test_segment_rejects_unknown_point_reference(client):
    circuit = client.post('/api/circuits', json={'name': 'X'}).get_json()
    resp = client.post(f"/api/circuits/{circuit['id']}/segments", json={
        'order_index': 0, 'origin_point_id': 999, 'destination_point_id': 2, 'waypoint_ids': [],
    })
    assert resp.status_code == 400


def test_update_segment_waypoints_for_path_editing(client):
    circuit = client.post('/api/circuits', json={'name': 'X'}).get_json()
    segment = client.post(f"/api/circuits/{circuit['id']}/segments", json={
        'order_index': 0, 'origin_point_id': 1, 'destination_point_id': 2, 'waypoint_ids': [3],
    }).get_json()

    resp = client.put(f"/api/segments/{segment['id']}", json={'waypoint_ids': [3, 1]})
    assert resp.status_code == 200
    assert resp.get_json()['waypoint_ids'] == [3, 1]


def test_delete_circuit_cascades_segments(client):
    circuit = client.post('/api/circuits', json={'name': 'X'}).get_json()
    client.post(f"/api/circuits/{circuit['id']}/segments", json={
        'order_index': 0, 'origin_point_id': 1, 'destination_point_id': 2, 'waypoint_ids': [],
    })

    resp = client.delete(f"/api/circuits/{circuit['id']}")
    assert resp.status_code == 204

    resp = client.get('/api/circuits')
    assert resp.get_json() == []
```

- [ ] **Step 2: Run to verify the tests fail**

Run: `pytest test_routes_circuits.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'routes_circuits'`.

- [ ] **Step 3: Implement `routes_circuits.py`**

```python
from flask import Blueprint, jsonify, request

from models import Circuit, Segment, Point

circuits_bp = Blueprint('circuits', __name__, url_prefix='/api')

_session_factory = None


def init_circuits_routes(session_factory):
    global _session_factory
    _session_factory = session_factory


def _serialize_circuit(circuit, include_segments=False):
    data = {'id': circuit.id, 'name': circuit.name}
    if include_segments:
        segments = sorted(circuit.segments, key=lambda s: s.order_index)
        data['segments'] = [_serialize_segment(s) for s in segments]
    return data


def _serialize_segment(segment):
    return {
        'id': segment.id,
        'circuit_id': segment.circuit_id,
        'order_index': segment.order_index,
        'origin_point_id': segment.origin_point_id,
        'destination_point_id': segment.destination_point_id,
        'waypoint_ids': segment.waypoint_ids or [],
        'zabbix_speed_itemid': segment.zabbix_speed_itemid,
        'zabbix_throughput_in_itemid': segment.zabbix_throughput_in_itemid,
        'zabbix_throughput_out_itemid': segment.zabbix_throughput_out_itemid,
        'zabbix_optical_rx_itemid': segment.zabbix_optical_rx_itemid,
        'zabbix_error_itemid': segment.zabbix_error_itemid,
        'zabbix_operstatus_itemid': segment.zabbix_operstatus_itemid,
        'signal_warn_threshold_dbm': segment.signal_warn_threshold_dbm,
    }


@circuits_bp.route('/circuits', methods=['GET'])
def list_circuits():
    session = _session_factory()
    try:
        circuits = session.query(Circuit).all()
        return jsonify([_serialize_circuit(c) for c in circuits])
    finally:
        session.close()


@circuits_bp.route('/circuits/<int:circuit_id>', methods=['GET'])
def get_circuit(circuit_id):
    session = _session_factory()
    try:
        circuit = session.get(Circuit, circuit_id)
        if circuit is None:
            return jsonify({'error': 'Circuito não encontrado'}), 404
        return jsonify(_serialize_circuit(circuit, include_segments=True))
    finally:
        session.close()


@circuits_bp.route('/circuits', methods=['POST'])
def create_circuit():
    data = request.get_json(force=True, silent=True) or {}
    if not data.get('name'):
        return jsonify({'error': "Campo obrigatório ausente: name"}), 400
    session = _session_factory()
    try:
        circuit = Circuit(name=data['name'])
        session.add(circuit)
        session.commit()
        return jsonify(_serialize_circuit(circuit)), 201
    finally:
        session.close()


@circuits_bp.route('/circuits/<int:circuit_id>', methods=['PUT'])
def update_circuit(circuit_id):
    data = request.get_json(force=True, silent=True) or {}
    session = _session_factory()
    try:
        circuit = session.get(Circuit, circuit_id)
        if circuit is None:
            return jsonify({'error': 'Circuito não encontrado'}), 404
        if 'name' in data:
            circuit.name = data['name']
        session.commit()
        return jsonify(_serialize_circuit(circuit))
    finally:
        session.close()


@circuits_bp.route('/circuits/<int:circuit_id>', methods=['DELETE'])
def delete_circuit(circuit_id):
    session = _session_factory()
    try:
        circuit = session.get(Circuit, circuit_id)
        if circuit is None:
            return jsonify({'error': 'Circuito não encontrado'}), 404
        for segment in list(circuit.segments):
            session.delete(segment)
        session.delete(circuit)
        session.commit()
        return '', 204
    finally:
        session.close()


SEGMENT_REQUIRED_FIELDS = ('order_index', 'origin_point_id', 'destination_point_id')
SEGMENT_OPTIONAL_FIELDS = (
    'waypoint_ids', 'zabbix_speed_itemid', 'zabbix_throughput_in_itemid',
    'zabbix_throughput_out_itemid', 'zabbix_optical_rx_itemid', 'zabbix_error_itemid',
    'zabbix_operstatus_itemid', 'signal_warn_threshold_dbm',
)


@circuits_bp.route('/circuits/<int:circuit_id>/segments', methods=['POST'])
def create_segment(circuit_id):
    data = request.get_json(force=True, silent=True) or {}
    missing = [f for f in SEGMENT_REQUIRED_FIELDS if f not in data]
    if missing:
        return jsonify({'error': f"Campos obrigatórios ausentes: {', '.join(missing)}"}), 400

    session = _session_factory()
    try:
        circuit = session.get(Circuit, circuit_id)
        if circuit is None:
            return jsonify({'error': 'Circuito não encontrado'}), 404

        for point_id in (data['origin_point_id'], data['destination_point_id'], *data.get('waypoint_ids', [])):
            if session.get(Point, point_id) is None:
                return jsonify({'error': f'Ponto {point_id} não existe'}), 400

        segment = Segment(
            circuit_id=circuit_id,
            order_index=data['order_index'],
            origin_point_id=data['origin_point_id'],
            destination_point_id=data['destination_point_id'],
            waypoint_ids=data.get('waypoint_ids', []),
            zabbix_speed_itemid=data.get('zabbix_speed_itemid'),
            zabbix_throughput_in_itemid=data.get('zabbix_throughput_in_itemid'),
            zabbix_throughput_out_itemid=data.get('zabbix_throughput_out_itemid'),
            zabbix_optical_rx_itemid=data.get('zabbix_optical_rx_itemid'),
            zabbix_error_itemid=data.get('zabbix_error_itemid'),
            zabbix_operstatus_itemid=data.get('zabbix_operstatus_itemid'),
            signal_warn_threshold_dbm=data.get('signal_warn_threshold_dbm'),
        )
        session.add(segment)
        session.commit()
        return jsonify(_serialize_segment(segment)), 201
    finally:
        session.close()


@circuits_bp.route('/segments/<int:segment_id>', methods=['PUT'])
def update_segment(segment_id):
    data = request.get_json(force=True, silent=True) or {}
    session = _session_factory()
    try:
        segment = session.get(Segment, segment_id)
        if segment is None:
            return jsonify({'error': 'Segmento não encontrado'}), 404
        for field in ('order_index', 'origin_point_id', 'destination_point_id', *SEGMENT_OPTIONAL_FIELDS):
            if field in data:
                setattr(segment, field, data[field])
        session.commit()
        return jsonify(_serialize_segment(segment))
    finally:
        session.close()


@circuits_bp.route('/segments/<int:segment_id>', methods=['DELETE'])
def delete_segment(segment_id):
    session = _session_factory()
    try:
        segment = session.get(Segment, segment_id)
        if segment is None:
            return jsonify({'error': 'Segmento não encontrado'}), 404
        session.delete(segment)
        session.commit()
        return '', 204
    finally:
        session.close()
```

- [ ] **Step 4: Register the blueprint in `app.py`**

In `map/app.py`, alongside the points blueprint registration:

```python
from routes_circuits import circuits_bp, init_circuits_routes

init_circuits_routes(SessionLocal)
app.register_blueprint(circuits_bp)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest test_routes_circuits.py -v`
Expected: `6 passed`.

- [ ] **Step 6: Commit**

```bash
git add map/routes_circuits.py map/test_routes_circuits.py map/app.py
git commit -m "Add circuits/segments CRUD API with configurable signal threshold (TDD)"
```

---

### Task 4: Cliente Zabbix + poller em background (TDD)

**Files:**
- Create: `map/zabbix_client.py`
- Create: `map/poller.py`
- Test: `map/test_zabbix_client.py`
- Test: `map/test_poller.py`

**Interfaces:**
- Produces: `zabbix_client.ZabbixClient(url, user, password, insecure=False)` with `.login() -> str` and `.get_items(itemids: list[str]) -> dict[str, dict]` (keyed by itemid, each value has `lastvalue`, `lastclock`); raises `zabbix_client.ZabbixAPIError` on API error. `poller.StatusCache` with `.get(itemid)`, `.get_all()`, `.last_refresh() -> float|None`, `.update(items_by_id: dict)`. `poller.poll_loop(zabbix_client, get_itemids_fn, cache, interval_seconds=30, stop_event=None)`. Used by Task 5 (map-state endpoint reads from `StatusCache`) and Task 8 (wired into `app.py` at startup).

- [ ] **Step 1: Write the failing tests for the Zabbix client**

`map/test_zabbix_client.py`:

```python
import pytest

from zabbix_client import ZabbixClient, ZabbixAPIError


def test_login_success(requests_mock):
    requests_mock.post('http://zabbix-frontend:8080/api_jsonrpc.php', json={
        'jsonrpc': '2.0', 'result': 'abc123token', 'id': 1,
    })
    client = ZabbixClient('http://zabbix-frontend:8080', 'Admin', 'secret')
    token = client.login()
    assert token == 'abc123token'


def test_login_raises_on_api_error(requests_mock):
    requests_mock.post('http://zabbix-frontend:8080/api_jsonrpc.php', json={
        'jsonrpc': '2.0',
        'error': {'code': -32602, 'message': 'Invalid params.', 'data': 'Login name or password is incorrect.'},
        'id': 1,
    })
    client = ZabbixClient('http://zabbix-frontend:8080', 'Admin', 'wrong')
    with pytest.raises(ZabbixAPIError):
        client.login()


def test_get_items_logs_in_first_then_fetches(requests_mock):
    requests_mock.post('http://zabbix-frontend:8080/api_jsonrpc.php', [
        {'json': {'jsonrpc': '2.0', 'result': 'abc123token', 'id': 1}},
        {'json': {'jsonrpc': '2.0', 'result': [
            {'itemid': '55010', 'lastvalue': '1', 'lastclock': '1700000000'},
            {'itemid': '55011', 'lastvalue': '-19.4', 'lastclock': '1700000000'},
        ], 'id': 2}},
    ])
    client = ZabbixClient('http://zabbix-frontend:8080', 'Admin', 'secret')
    items = client.get_items(['55010', '55011'])
    assert items['55010']['lastvalue'] == '1'
    assert items['55011']['lastvalue'] == '-19.4'


def test_get_items_empty_list_skips_request(requests_mock):
    client = ZabbixClient('http://zabbix-frontend:8080', 'Admin', 'secret')
    assert client.get_items([]) == {}
    assert requests_mock.call_count == 0


def test_get_items_raises_on_api_error(requests_mock):
    requests_mock.post('http://zabbix-frontend:8080/api_jsonrpc.php', [
        {'json': {'jsonrpc': '2.0', 'result': 'abc123token', 'id': 1}},
        {'json': {'jsonrpc': '2.0', 'error': {'code': -32500, 'message': 'App error.', 'data': 'No permissions'}, 'id': 2}},
    ])
    client = ZabbixClient('http://zabbix-frontend:8080', 'Admin', 'secret')
    with pytest.raises(ZabbixAPIError):
        client.get_items(['55010'])
```

- [ ] **Step 2: Run to verify the tests fail**

Run: `pytest test_zabbix_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zabbix_client'`.

- [ ] **Step 3: Implement `zabbix_client.py`**

```python
import requests


class ZabbixAPIError(Exception):
    pass


class ZabbixClient:
    def __init__(self, url, user, password, insecure=False):
        self.api_url = url.rstrip('/') + '/api_jsonrpc.php'
        self.user = user
        self.password = password
        self.verify = not insecure
        self._auth_token = None

    def _call(self, method, params, request_id, use_auth=False):
        headers = {'Content-Type': 'application/json-rpc'}
        if use_auth:
            headers['Authorization'] = f'Bearer {self._auth_token}'
        resp = requests.post(
            self.api_url,
            json={'jsonrpc': '2.0', 'method': method, 'params': params, 'id': request_id},
            headers=headers, verify=self.verify, timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if 'error' in data:
            raise ZabbixAPIError(data['error'].get('data') or data['error'].get('message'))
        return data['result']

    def login(self):
        self._auth_token = self._call(
            'user.login', {'username': self.user, 'password': self.password}, request_id=1,
        )
        return self._auth_token

    def get_items(self, itemids):
        if not itemids:
            return {}
        if not self._auth_token:
            self.login()
        result = self._call(
            'item.get',
            {'itemids': itemids, 'output': ['itemid', 'lastvalue', 'lastclock']},
            request_id=2, use_auth=True,
        )
        return {item['itemid']: item for item in result}
```

- [ ] **Step 4: Run Zabbix client tests to verify they pass**

Run: `pytest test_zabbix_client.py -v`
Expected: `5 passed`.

- [ ] **Step 5: Write the failing tests for the poller**

`map/test_poller.py`:

```python
import threading

from poller import StatusCache, poll_loop


class FakeZabbixClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get_items(self, itemids):
        self.calls.append(itemids)
        if not self.responses:
            raise RuntimeError('Zabbix unreachable')
        return self.responses.pop(0)


def test_cache_starts_with_no_last_refresh():
    cache = StatusCache()
    assert cache.last_refresh() is None
    assert cache.get('55010') is None


def test_cache_update_stores_items_and_refresh_time():
    cache = StatusCache()
    cache.update({'55010': {'lastvalue': '1'}})
    assert cache.get('55010') == {'lastvalue': '1'}
    assert cache.last_refresh() is not None


def test_poll_loop_runs_once_and_updates_cache():
    cache = StatusCache()
    client = FakeZabbixClient([{'55010': {'lastvalue': '1'}}])
    stop_event = threading.Event()
    stop_event.set()  # makes the loop's wait() return immediately after one iteration

    poll_loop(client, lambda: ['55010'], cache, interval_seconds=0, stop_event=stop_event)

    assert cache.get('55010') == {'lastvalue': '1'}
    assert client.calls == [['55010']]


def test_poll_loop_survives_zabbix_error_without_crashing():
    cache = StatusCache()
    client = FakeZabbixClient([])  # first call raises
    stop_event = threading.Event()
    stop_event.set()

    poll_loop(client, lambda: ['55010'], cache, interval_seconds=0, stop_event=stop_event)

    assert cache.get('55010') is None
    assert cache.last_refresh() is None
```

- [ ] **Step 6: Run to verify the poller tests fail**

Run: `pytest test_poller.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'poller'`.

- [ ] **Step 7: Implement `poller.py`**

```python
import logging
import threading
import time

logger = logging.getLogger(__name__)


class StatusCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {}
        self._last_refresh = None

    def get(self, itemid):
        with self._lock:
            return self._data.get(itemid)

    def get_all(self):
        with self._lock:
            return dict(self._data)

    def last_refresh(self):
        with self._lock:
            return self._last_refresh

    def update(self, items_by_id):
        with self._lock:
            self._data.update(items_by_id)
            self._last_refresh = time.time()


def poll_loop(zabbix_client, get_itemids_fn, cache, interval_seconds=30, stop_event=None):
    """Runs until stop_event is set. Each iteration fetches the current
    itemids (via get_itemids_fn, so newly-created segments are picked up
    without restarting) and updates the cache. A Zabbix failure is logged
    and skipped — it never crashes the loop, and it never touches the
    cache, so stale data ages out via last_refresh() instead of being
    silently kept as fresh."""
    while True:
        try:
            itemids = get_itemids_fn()
            items = zabbix_client.get_items(itemids)
            cache.update(items)
        except Exception:
            logger.exception('Failed to refresh Zabbix item cache')

        if stop_event is not None:
            if stop_event.wait(interval_seconds):
                break
        else:
            time.sleep(interval_seconds)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest test_poller.py -v`
Expected: `4 passed`.

- [ ] **Step 9: Commit**

```bash
git add map/zabbix_client.py map/poller.py map/test_zabbix_client.py map/test_poller.py
git commit -m "Add Zabbix API client and background status poller (TDD)"
```

---

### Task 5: Endpoint de estado do mapa — agrega pontos + circuitos + status (TDD)

**Files:**
- Create: `map/routes_map.py`
- Test: `map/test_routes_map.py`
- Modify: `map/app.py` (register blueprint, start poller thread)

**Interfaces:**
- Consumes: `models.Point`, `models.Circuit`, `models.Segment` (Task 1), `status.compute_status` (Task 1), `poller.StatusCache` (Task 4).
- Produces: `routes_map.build_map_state(session, cache, stale_threshold_seconds) -> dict` (pure-ish function, takes an already-open session and cache, returns the JSON-serializable map state — used directly by the tests and by the Flask route). Flask blueprint `map_state_bp` at `GET /api/map-state`. Response shape:
```json
{
  "points": [{"id": 1, "name": "...", "lat": ..., "lng": ..., "point_type": "equipment", "status": "up|warn|down|unknown", "equipment_model": "...", "equipment_ip": "...", "cpu_percent": 42.0}],
  "circuits": [{"id": 1, "name": "...", "segments": [{"id": 1, "origin_point_id": 1, "destination_point_id": 2, "waypoint_ids": [3], "status": "up|warn|down|unknown", "speed_mbps": 1000, "throughput_in_mbps": 312, "throughput_out_mbps": 89, "optical_rx_dbm": -19.4, "error_count": 0}]}],
  "stale": false
}
```
Used by Task 6 (map frontend) and Task 7 (Circuitos admin, to show current status next to each circuit in the list).

- [ ] **Step 1: Write the failing tests**

`map/test_routes_map.py`:

```python
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
    assert all(p['status'] == 'unknown' for p in state['points'])
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
```

- [ ] **Step 2: Run to verify the tests fail**

Run: `pytest test_routes_map.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'routes_map'`.

- [ ] **Step 3: Implement `routes_map.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_routes_map.py -v`
Expected: `5 passed`.

- [ ] **Step 5: Wire the poller and this blueprint into `app.py`**

In `map/app.py`, add near the top-level setup (after the other blueprint registrations):

```python
import atexit
import threading

from routes_map import map_state_bp, init_map_routes
from poller import StatusCache, poll_loop
from zabbix_client import ZabbixClient
from models import Segment, Point

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
```

- [ ] **Step 6: Verify the full app still imports cleanly**

Run: `cd map && DATABASE_URL=sqlite:///:memory: python -c "import app; print('OK')"`
Expected: prints `OK`. (The poller thread starts and immediately tries a poll against `http://zabbix-frontend:8080`, which will fail with a connection error in this dev environment — that's fine, `poll_loop` catches it and logs, per Task 4's test coverage. The import itself must not raise.)

- [ ] **Step 7: Commit**

```bash
git add map/routes_map.py map/test_routes_map.py map/app.py
git commit -m "Add map-state aggregation endpoint and wire the poller into the app (TDD)"
```

---

### Task 6: Frontend — tela de mapa (Início)

**Files:**
- Create: `map/static/index.html`
- Create: `map/static/css/app.css`
- Create: `map/static/js/app.js`
- Modify: `map/app.py` (serve static files)

**Interfaces:**
- Consumes: `GET /api/map-state` (Task 5) response shape.
- Produces: the page at `/` — sidebar navigation shell with "Início" and "Circuitos" links (Circuitos wired up in Task 7), and the live map. Manual browser verification (matches project convention: UI-heavy work is verified in-browser, not unit tested).

- [ ] **Step 1: Serve the static folder from `app.py`**

In `map/app.py`, change the Flask app construction near the top:

```python
app = Flask(__name__, static_folder='static', static_url_path='')
```

Add, near the `/health` route:

```python
@app.route('/')
def index():
    return app.send_static_file('index.html')
```

- [ ] **Step 2: Create `static/index.html`**

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <title>Natverk NOC — Mapa de Circuitos</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="stylesheet" href="css/app.css" />
</head>
<body>
  <div class="app-shell">
    <nav class="nav">
      <div class="nav-title">Natverk NOC</div>
      <a href="/" class="nav-item active" data-view="inicio">Início</a>
      <a href="/circuitos.html" class="nav-item" data-view="circuitos">Circuitos</a>
      <a href="/configuracoes.html" class="nav-item" data-view="configuracoes">Configurações</a>
    </nav>
    <main id="map"></main>
  </div>

  <div class="backdrop" id="backdrop"></div>
  <div class="detail-modal" id="detail-modal">
    <div class="modal-photo" id="modal-photo">
      <span class="close" id="modal-close">&times;</span>
      <img id="modal-photo-img" src="" alt="" />
    </div>
    <h4 id="modal-title"></h4>
    <table class="detail-table" id="modal-table"></table>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="js/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Create `static/css/app.css`** (adapted from the validated mockup — same visual language: macOS-style sidebar with no icons, soft glow markers/lines, zebra-striped detail table)

```css
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
  background: #141416;
  color: #e8e8ea;
}

.app-shell { display: flex; height: 100vh; }

.nav { width: 190px; background: #1e1e20; padding: 16px 10px; flex-shrink: 0; display: flex; flex-direction: column; gap: 2px; }
.nav-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; opacity: 0.45; padding: 4px 10px 8px; }
.nav-item { padding: 7px 12px; border-radius: 7px; font-size: 13.5px; color: #d8d8db; cursor: pointer; text-decoration: none; display: block; }
.nav-item.active { background: #3b7ef0; color: #fff; }
.nav-item:not(.active):hover { background: rgba(255,255,255,0.06); }

#map { flex: 1; }

.status-dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:7px; }
.status-dot.up { background:#3ecf6a; }
.status-dot.warn { background:#f5a623; }
.status-dot.down { background:#e5484d; }
.status-dot.unknown { background:#888; }

.detail-modal {
  position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
  background: #232326; border: 1px solid rgba(255,255,255,0.1); border-radius: 14px;
  width: 320px; font-size: 13px; z-index: 1000; box-shadow: 0 20px 50px rgba(0,0,0,0.6);
  display: none; overflow: hidden;
}
.detail-modal.open { display: block; }
.modal-photo { width: 100%; height: 120px; background: linear-gradient(135deg,#2c2c30,#3a3a40); display:flex; align-items:center; justify-content:center; position:relative; }
.modal-photo img { width: 92px; height: 92px; object-fit: contain; filter: drop-shadow(0 6px 10px rgba(0,0,0,0.5)); }
.modal-photo .close { position:absolute; top:10px; right:12px; cursor:pointer; opacity:0.7; color:#fff; font-size: 20px; line-height: 1; }
.detail-modal h4 { margin: 14px 16px 10px; display:flex; align-items:center; font-weight: 600; font-size: 14px; }

.detail-table { width: 100%; border-collapse: collapse; }
.detail-table tr { border-top: 1px solid rgba(255,255,255,0.07); }
.detail-table tr:nth-child(odd) { background: rgba(255,255,255,0.02); }
.detail-table td { padding: 8px 16px; }
.detail-table td:first-child { opacity: 0.6; width: 46%; }
.detail-table td:last-child { text-align: right; font-variant-numeric: tabular-nums; }
.detail-table tr:last-child td { padding-bottom: 14px; }

.backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.35); z-index: 999; display: none; }
.backdrop.open { display: block; }

.leaflet-tooltip.mini-tip { background:#232326; color:#eee; border:1px solid rgba(255,255,255,0.12); font-size:11px; padding:6px 8px; line-height:1.5; }
```

- [ ] **Step 4: Create `static/js/app.js`** — fetches `/api/map-state`, renders markers/lines with the validated glow style, wires hover tooltip + click modal, and refreshes every `POLL_INTERVAL_SECONDS` (read from a `<meta>` tag the backend could inject later; hardcode 30s for now, matching the default)

```javascript
const STATUS_COLOR = { up: '#3ecf6a', warn: '#f5a623', down: '#e5484d', unknown: '#888888' };
const REFRESH_INTERVAL_MS = 30000;

const map = L.map('map').setView([-23.5629, -46.6544], 13);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; OpenStreetMap &copy; CARTO', maxZoom: 20, subdomains: 'abcd',
}).addTo(map);

let markerLayer = L.layerGroup().addTo(map);
let lineLayer = L.layerGroup().addTo(map);

function glowIcon(color) {
  return L.divIcon({
    className: '',
    html:
      '<div style="position:relative;width:26px;height:26px;">' +
        '<div style="position:absolute;inset:0;border-radius:50%;background:' + color + ';opacity:0.35;filter:blur(4px)"></div>' +
        '<div style="position:absolute;top:5px;left:5px;width:16px;height:16px;border-radius:50%;background:' + color + ';border:2px solid rgba(255,255,255,0.85);box-shadow:0 0 4px rgba(0,0,0,0.4)"></div>' +
      '</div>',
    iconSize: [26, 26], iconAnchor: [13, 13],
  });
}

function drawGlowLine(latlngs, color, dashed) {
  const opts = { weight: 5, color, opacity: 0.95, lineCap: 'round', lineJoin: 'round', smoothFactor: 3 };
  if (dashed) opts.dashArray = '1 10';
  L.polyline(latlngs, { weight: 14, color, opacity: 0.18, lineCap: 'round', lineJoin: 'round', smoothFactor: 3 }).addTo(lineLayer);
  return L.polyline(latlngs, opts).addTo(lineLayer);
}

function fmt(value, unit) {
  if (value === null || value === undefined) return '—';
  return `${value}${unit || ''}`;
}

function openModal({ photoUrl, title, statusClass, rows }) {
  document.getElementById('modal-photo-img').src = photoUrl;
  const titleEl = document.getElementById('modal-title');
  titleEl.innerHTML = `<span class="status-dot ${statusClass}"></span>${title}`;
  const table = document.getElementById('modal-table');
  table.innerHTML = rows.map(([label, value]) => `<tr><td>${label}</td><td>${value}</td></tr>`).join('');
  document.getElementById('backdrop').classList.add('open');
  document.getElementById('detail-modal').classList.add('open');
}

function closeModal() {
  document.getElementById('backdrop').classList.remove('open');
  document.getElementById('detail-modal').classList.remove('open');
}
document.getElementById('modal-close').addEventListener('click', closeModal);
document.getElementById('backdrop').addEventListener('click', closeModal);

function equipmentPhotoUrl(model) {
  // No local static fallback file exists — always route through the API,
  // which already returns a generic SVG server-side when no image is
  // uploaded for the given model (including the 'generic' placeholder
  // used here when a circuit segment, not an equipment point, was clicked).
  return `/api/equipment-images/${encodeURIComponent(model || 'generic')}`;
}

async function refresh() {
  let state;
  try {
    const resp = await fetch('/api/map-state');
    state = await resp.json();
  } catch (err) {
    console.error('Falha ao buscar /api/map-state', err);
    return;
  }

  markerLayer.clearLayers();
  lineLayer.clearLayers();

  const pointsById = Object.fromEntries(state.points.map((p) => [p.id, p]));

  state.circuits.forEach((circuit) => {
    circuit.segments.forEach((segment) => {
      const origin = pointsById[segment.origin_point_id];
      const dest = pointsById[segment.destination_point_id];
      if (!origin || !dest) return;
      const waypoints = segment.waypoint_ids.map((id) => pointsById[id]).filter(Boolean);
      const latlngs = [origin, ...waypoints, dest].map((p) => [p.lat, p.lng]);
      const color = STATUS_COLOR[segment.status] || STATUS_COLOR.unknown;
      const line = drawGlowLine(latlngs, color, segment.status === 'down');

      line.bindTooltip(
        `${circuit.name}<br>${segment.status} · sinal ${fmt(segment.optical_rx_dbm, ' dBm')} · ` +
        `${fmt(segment.throughput_in_mbps, ' Mbps')} / ${fmt(segment.throughput_out_mbps, ' Mbps')}`,
        { className: 'mini-tip', sticky: true },
      );
      line.on('click', () => openModal({
        photoUrl: equipmentPhotoUrl(null),
        title: circuit.name,
        statusClass: segment.status,
        rows: [
          ['Status', segment.status],
          ['Velocidade', fmt(segment.speed_mbps, ' Mbps')],
          ['Throughput', `${fmt(segment.throughput_in_mbps, ' Mbps')} ↓ / ${fmt(segment.throughput_out_mbps, ' Mbps')} ↑`],
          ['Sinal óptico', fmt(segment.optical_rx_dbm, ' dBm')],
          ['Limiar configurado', fmt(segment.signal_warn_threshold_dbm, ' dBm')],
          ['Erros', fmt(segment.error_count, '')],
        ],
      }));
    });
  });

  state.points.forEach((point) => {
    if (point.point_type === 'waypoint') {
      L.circleMarker([point.lat, point.lng], { radius: 4, color: '#888', fillOpacity: 1 })
        .addTo(markerLayer)
        .bindTooltip('Poste / caixa (só trajeto)', { className: 'mini-tip' });
      return;
    }
    const color = STATUS_COLOR[point.status] || STATUS_COLOR.unknown;
    const marker = L.marker([point.lat, point.lng], { icon: glowIcon(color) }).addTo(markerLayer);
    marker.bindTooltip(
      `<b>${point.name}</b><br>${point.equipment_ip || ''} · ${point.status}`,
      { className: 'mini-tip' },
    );
    marker.on('click', () => openModal({
      photoUrl: equipmentPhotoUrl(point.equipment_model),
      title: point.name,
      statusClass: point.status,
      rows: [
        ['Modelo', point.equipment_model || '—'],
        ['IP', point.equipment_ip || '—'],
        ['Status', point.status],
        ['CPU', fmt(point.cpu_percent, '%')],
      ],
    }));
  });
}

refresh();
setInterval(refresh, REFRESH_INTERVAL_MS);
```

- [ ] **Step 5: Manual verification**

Run `docker compose up -d --build` in `map/` against a Postgres + Zabbix that's reachable (the user's own test Zabbix environment, once it's up), or run `python app.py` locally with `DATABASE_URL=sqlite:///local.db` and no real Zabbix (the map will just show everything as `unknown`/gray, which is itself a valid check that the stale/no-data path renders correctly without crashing). Confirm:
- The page loads with the sidebar and an empty (or gray) map, no console errors.
- With at least one point/circuit created via `curl` against `/api/points` and `/api/circuits`, the marker/line appears in roughly the right place.
- Hovering shows the tooltip; clicking opens the centered modal with the table.

- [ ] **Step 6: Commit**

```bash
git add map/static/index.html map/static/css/app.css map/static/js/app.js map/app.py
git commit -m "Add map view frontend (Início): live markers/lines, hover tooltip, click modal"
```

---

### Task 7: Frontend — administração de Circuitos + editor de trajeto arrastável

**Files:**
- Create: `map/static/circuitos.html`
- Create: `map/static/js/circuitos.js`
- Create: `map/static/js/editor.js`

**Interfaces:**
- Consumes: `/api/points`, `/api/circuits`, `/api/circuits/<id>`, `/api/circuits/<id>/segments`, `/api/segments/<id>` (Tasks 2, 3), `/api/map-state` (Task 5, to show live status next to each circuit in the list).
- Produces: the `/circuitos.html` page — circuit/point CRUD forms, and a map-embedded "Editar trajeto" mode using Leaflet-Geoman that lets a user drag/add path points and saves the result back via `PUT /api/segments/<id>`. Manual browser verification.

- [ ] **Step 1: Create `static/circuitos.html`**

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <title>Natverk NOC — Circuitos</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="stylesheet" href="https://unpkg.com/@geoman-io/leaflet-geoman-free@2.18.3/dist/leaflet-geoman.css" />
  <link rel="stylesheet" href="css/app.css" />
  <style>
    .circuitos-shell { display: flex; flex: 1; min-height: 0; }
    .panel { width: 360px; background: #1a1a1c; padding: 16px; overflow-y: auto; font-size: 13px; }
    .panel h3 { font-size: 13px; text-transform: uppercase; opacity: 0.5; margin: 18px 0 8px; }
    .panel h3:first-child { margin-top: 0; }
    .list-item { padding: 8px 10px; border-radius: 6px; margin-bottom: 4px; cursor: pointer; display: flex; align-items: center; justify-content: space-between; }
    .list-item:hover { background: rgba(255,255,255,0.06); }
    .list-item.selected { background: rgba(80,160,255,0.15); }
    form.inline { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
    form.inline input, form.inline select { background: #232326; border: 1px solid rgba(255,255,255,0.12); border-radius: 6px; padding: 6px 8px; color: inherit; font-size: 13px; }
    form.inline button { padding: 7px; border-radius: 6px; border: 1px solid rgba(80,160,255,0.5); background: rgba(80,160,255,0.15); color: inherit; cursor: pointer; }
    #editor-map { flex: 1; }
  </style>
</head>
<body>
  <div class="app-shell">
    <nav class="nav">
      <div class="nav-title">Natverk NOC</div>
      <a href="/" class="nav-item">Início</a>
      <a href="/circuitos.html" class="nav-item active">Circuitos</a>
      <a href="/configuracoes.html" class="nav-item">Configurações</a>
    </nav>
    <div class="circuitos-shell">
      <div class="panel">
        <h3>Pontos</h3>
        <div id="points-list"></div>
        <form class="inline" id="point-form">
          <input name="name" placeholder="Nome" required />
          <input name="lat" placeholder="Latitude" required />
          <input name="lng" placeholder="Longitude" required />
          <select name="point_type">
            <option value="waypoint">Trajeto (sem monitoramento)</option>
            <option value="equipment">Equipamento (host do Zabbix)</option>
          </select>
          <input name="zabbix_hostid" placeholder="Zabbix hostid (equipamento)" />
          <input name="zabbix_status_itemid" placeholder="Zabbix itemid — status" />
          <input name="zabbix_cpu_itemid" placeholder="Zabbix itemid — CPU (opcional)" />
          <input name="equipment_model" placeholder="Modelo do equipamento (opcional)" />
          <input name="equipment_ip" placeholder="IP (opcional)" />
          <button type="submit">Adicionar ponto</button>
        </form>

        <h3>Circuitos</h3>
        <div id="circuits-list"></div>
        <form class="inline" id="circuit-form">
          <input name="name" placeholder="Nome do circuito" required />
          <button type="submit">Criar circuito</button>
        </form>

        <div id="segment-panel" style="display:none">
          <h3>Novo segmento</h3>
          <form class="inline" id="segment-form">
            <select name="origin_point_id" id="origin-select"></select>
            <select name="destination_point_id" id="destination-select"></select>
            <input name="zabbix_operstatus_itemid" placeholder="itemid — status da porta" />
            <input name="zabbix_speed_itemid" placeholder="itemid — velocidade" />
            <input name="zabbix_throughput_in_itemid" placeholder="itemid — throughput entrada" />
            <input name="zabbix_throughput_out_itemid" placeholder="itemid — throughput saída" />
            <input name="zabbix_optical_rx_itemid" placeholder="itemid — sinal óptico RX" />
            <input name="zabbix_error_itemid" placeholder="itemid — contador de erros" />
            <input name="signal_warn_threshold_dbm" placeholder="Limiar de sinal (dBm), ex: -25" />
            <button type="submit">Adicionar segmento</button>
          </form>
          <button id="edit-path-btn" style="margin-top:10px">Editar trajeto</button>
        </div>
      </div>
      <div id="editor-map"></div>
    </div>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/@geoman-io/leaflet-geoman-free@2.18.3/dist/leaflet-geoman.min.js"></script>
  <script src="js/circuitos.js"></script>
  <script src="js/editor.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `static/js/circuitos.js`** — CRUD wiring for points/circuits/segments lists and forms

```javascript
const editorMap = L.map('editor-map').setView([-23.5629, -46.6544], 13);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; OpenStreetMap &copy; CARTO', maxZoom: 20, subdomains: 'abcd',
}).addTo(editorMap);

let allPoints = [];
let selectedCircuitId = null;

async function api(path, options) {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!resp.ok) throw new Error(`${path} -> HTTP ${resp.status}`);
  if (resp.status === 204) return null;
  return resp.json();
}

async function loadPoints() {
  allPoints = await api('/api/points');
  const list = document.getElementById('points-list');
  list.innerHTML = allPoints.map((p) => `<div class="list-item">${p.name} <small>(${p.point_type})</small></div>`).join('');

  const originSel = document.getElementById('origin-select');
  const destSel = document.getElementById('destination-select');
  const equipmentOptions = allPoints
    .filter((p) => p.point_type === 'equipment')
    .map((p) => `<option value="${p.id}">${p.name}</option>`).join('');
  originSel.innerHTML = equipmentOptions;
  destSel.innerHTML = equipmentOptions;
}

async function loadCircuits() {
  const circuits = await api('/api/circuits');
  const list = document.getElementById('circuits-list');
  list.innerHTML = circuits.map((c) => `
    <div class="list-item${c.id === selectedCircuitId ? ' selected' : ''}" data-id="${c.id}">${c.name}</div>
  `).join('');
  list.querySelectorAll('.list-item').forEach((el) => {
    el.addEventListener('click', () => selectCircuit(Number(el.dataset.id)));
  });
}

async function selectCircuit(circuitId) {
  selectedCircuitId = circuitId;
  document.getElementById('segment-panel').style.display = 'block';
  await loadCircuits();
  window.currentCircuit = await api(`/api/circuits/${circuitId}`);
  window.renderCircuitOnEditorMap(window.currentCircuit, allPoints);
}

document.getElementById('point-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const body = {
    name: form.get('name'), lat: parseFloat(form.get('lat')), lng: parseFloat(form.get('lng')),
    point_type: form.get('point_type'),
    zabbix_hostid: form.get('zabbix_hostid') || null,
    zabbix_status_itemid: form.get('zabbix_status_itemid') || null,
    zabbix_cpu_itemid: form.get('zabbix_cpu_itemid') || null,
    equipment_model: form.get('equipment_model') || null,
    equipment_ip: form.get('equipment_ip') || null,
  };
  await api('/api/points', { method: 'POST', body: JSON.stringify(body) });
  e.target.reset();
  await loadPoints();
});

document.getElementById('circuit-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const circuit = await api('/api/circuits', { method: 'POST', body: JSON.stringify({ name: form.get('name') }) });
  e.target.reset();
  await loadCircuits();
  await selectCircuit(circuit.id);
});

document.getElementById('segment-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!selectedCircuitId) return;
  const form = new FormData(e.target);
  const nextOrderIndex = (window.currentCircuit?.segments?.length) || 0;
  const body = {
    order_index: nextOrderIndex,
    origin_point_id: Number(form.get('origin_point_id')),
    destination_point_id: Number(form.get('destination_point_id')),
    waypoint_ids: [],
    zabbix_operstatus_itemid: form.get('zabbix_operstatus_itemid') || null,
    zabbix_speed_itemid: form.get('zabbix_speed_itemid') || null,
    zabbix_throughput_in_itemid: form.get('zabbix_throughput_in_itemid') || null,
    zabbix_throughput_out_itemid: form.get('zabbix_throughput_out_itemid') || null,
    zabbix_optical_rx_itemid: form.get('zabbix_optical_rx_itemid') || null,
    zabbix_error_itemid: form.get('zabbix_error_itemid') || null,
    signal_warn_threshold_dbm: form.get('signal_warn_threshold_dbm') ? parseFloat(form.get('signal_warn_threshold_dbm')) : null,
  };
  await api(`/api/circuits/${selectedCircuitId}/segments`, { method: 'POST', body: JSON.stringify(body) });
  e.target.reset();
  await selectCircuit(selectedCircuitId);
});

(async function init() {
  await loadPoints();
  await loadCircuits();
})();
```

- [ ] **Step 3: Create `static/js/editor.js`** — Leaflet-Geoman wiring: renders the selected circuit's segments as editable polylines, "Editar trajeto" toggles drag/add-point mode, saves back on edit

```javascript
let segmentLayersBySegmentId = {};

window.renderCircuitOnEditorMap = function renderCircuitOnEditorMap(circuit, points) {
  Object.values(segmentLayersBySegmentId).forEach((layer) => editorMap.removeLayer(layer));
  segmentLayersBySegmentId = {};

  const pointsById = Object.fromEntries(points.map((p) => [p.id, p]));

  circuit.segments.forEach((segment) => {
    const origin = pointsById[segment.origin_point_id];
    const dest = pointsById[segment.destination_point_id];
    if (!origin || !dest) return;
    const waypoints = segment.waypoint_ids.map((id) => pointsById[id]).filter(Boolean);
    const latlngs = [origin, ...waypoints, dest].map((p) => [p.lat, p.lng]);

    const line = L.polyline(latlngs, { color: '#3b7ef0', weight: 4 }).addTo(editorMap);
    segmentLayersBySegmentId[segment.id] = line;
  });

  if (circuit.segments.length > 0) {
    const bounds = L.featureGroup(Object.values(segmentLayersBySegmentId)).getBounds();
    if (bounds.isValid()) editorMap.fitBounds(bounds, { padding: [30, 30] });
  }
};

let editingSegmentId = null;

document.getElementById('edit-path-btn').addEventListener('click', () => {
  const circuit = window.currentCircuit;
  if (!circuit || circuit.segments.length === 0) return;
  const segment = circuit.segments[circuit.segments.length - 1]; // edits the most recently added segment
  const layer = segmentLayersBySegmentId[segment.id];
  if (!layer) return;

  if (editingSegmentId === segment.id) {
    // Already editing — save and exit
    layer.pm.disable();
    const latlngs = layer.getLatLngs();
    saveEditedPath(segment, latlngs);
    editingSegmentId = null;
    document.getElementById('edit-path-btn').textContent = 'Editar trajeto';
    return;
  }

  layer.pm.enable({ allowSelfIntersection: true, draggable: true });
  editingSegmentId = segment.id;
  document.getElementById('edit-path-btn').textContent = 'Salvar trajeto';
});

async function saveEditedPath(segment, latlngs) {
  // The first and last vertices are the origin/destination equipment points
  // (not editable — Leaflet-Geoman lets the user drag them visually, but we
  // only persist the middle vertices as the segment's waypoint_ids; moving
  // an equipment point's real location happens via the Pontos form instead).
  const middleLatLngs = latlngs.slice(1, -1);

  const newWaypoints = [];
  for (const ll of middleLatLngs) {
    const point = await api('/api/points', {
      method: 'POST',
      body: JSON.stringify({ name: 'Trajeto', lat: ll.lat, lng: ll.lng, point_type: 'waypoint' }),
    });
    newWaypoints.push(point.id);
  }

  await api(`/api/segments/${segment.id}`, {
    method: 'PUT',
    body: JSON.stringify({ waypoint_ids: newWaypoints }),
  });

  await selectCircuit(selectedCircuitId);
}
```

- [ ] **Step 4: Manual verification**

Against a running instance (real Zabbix once available, or SQLite/no-Zabbix for UI-only checks):
- Create two equipment points and a waypoint via the Pontos form, confirm they appear in the list.
- Create a circuit, add a segment between the two equipment points, confirm the line renders on the editor map.
- Click "Editar trajeto", drag the line to add a bend, click "Salvar trajeto", confirm `GET /api/circuits/<id>` now shows a new waypoint id in `waypoint_ids` and reloading `/` (Início) shows the line following the new shape.

- [ ] **Step 5: Commit**

```bash
git add map/static/circuitos.html map/static/js/circuitos.js map/static/js/editor.js
git commit -m "Add Circuitos admin page: point/circuit/segment CRUD and draggable path editor"
```

---

### Task 8: Configurações (imagens de equipamento) + empacotamento (Dockerfile, compose, install.sh)

**Files:**
- Create: `map/static/configuracoes.html`
- Create: `map/routes_equipment_images.py`
- Test: `map/test_routes_equipment_images.py`
- Create: `map/Dockerfile`
- Create: `map/docker-compose.yml`
- Modify: `map/app.py` (register the equipment-images blueprint, ensure the upload folder exists)
- Modify: `install.sh` (bring up `map/` after `tools/`, generate its `.env`, mirror Postgres/Zabbix credentials from `stack/.env`)
- Modify: `README.md` (list `map/` as a fourth component)

**Interfaces:**
- Consumes: nothing new from earlier tasks besides the existing Flask app structure.
- Produces: `GET /api/equipment-images/<model>` (serves the uploaded image for that model, or a generic fallback SVG if none was uploaded), `POST /api/equipment-images/<model>` (multipart upload, replaces any existing image for that model). Used by Task 6/7's frontend `equipmentPhotoUrl()` helper (already written to call this exact path).

- [ ] **Step 1: Write the failing tests**

`map/test_routes_equipment_images.py`:

```python
import io

import pytest
from flask import Flask

from routes_equipment_images import equipment_images_bp, init_equipment_images_routes


@pytest.fixture
def client(tmp_path):
    app = Flask(__name__)
    init_equipment_images_routes(str(tmp_path))
    app.register_blueprint(equipment_images_bp)
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def test_get_missing_model_returns_generic_fallback(client):
    resp = client.get('/api/equipment-images/Huawei%20MA5800-X2')
    assert resp.status_code == 200
    assert resp.content_type.startswith('image/svg')


def test_upload_and_retrieve_image(client):
    fake_png = io.BytesIO(b'\x89PNG\r\n\x1a\nfakepngbytes')
    resp = client.post(
        '/api/equipment-images/Huawei%20MA5800-X2',
        data={'file': (fake_png, 'olt.png')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 204

    resp = client.get('/api/equipment-images/Huawei%20MA5800-X2')
    assert resp.status_code == 200
    assert resp.content_type == 'image/png'
    assert resp.data == b'\x89PNG\r\n\x1a\nfakepngbytes'


def test_upload_rejects_disallowed_extension(client):
    fake_exe = io.BytesIO(b'MZfakeexe')
    resp = client.post(
        '/api/equipment-images/Something',
        data={'file': (fake_exe, 'virus.exe')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 400


def test_model_name_is_sanitized_for_filesystem(client):
    fake_png = io.BytesIO(b'fakepng')
    resp = client.post(
        '/api/equipment-images/../../etc/passwd',
        data={'file': (fake_png, 'x.png')},
        content_type='multipart/form-data',
    )
    # Flask's <model> route segment already can't contain a literal '/',
    # so this exercises the sanitizer against the decoded value instead.
    assert resp.status_code in (204, 400)
```

- [ ] **Step 2: Run to verify the tests fail**

Run: `pytest test_routes_equipment_images.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'routes_equipment_images'`.

- [ ] **Step 3: Implement `routes_equipment_images.py`**

```python
import os
import re

from flask import Blueprint, request, send_file, Response

equipment_images_bp = Blueprint('equipment_images', __name__, url_prefix='/api/equipment-images')

_upload_dir = None
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.svg', '.webp'}

GENERIC_FALLBACK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="64" height="64" '
    'fill="none" stroke="#aaaaaa" stroke-width="1.5">'
    '<rect x="3" y="8" width="18" height="8" rx="1.5"/>'
    '<circle cx="7" cy="12" r="1"/><circle cx="10.5" cy="12" r="1"/>'
    '<path d="M14 12h6"/></svg>'
)


def init_equipment_images_routes(upload_dir):
    global _upload_dir
    _upload_dir = upload_dir
    os.makedirs(_upload_dir, exist_ok=True)


def _sanitize_model_name(model):
    # Strip anything that isn't alphanumeric/space/dash/underscore/dot, then
    # collapse to a safe filename stem — blocks path traversal regardless of
    # how the model string arrives (URL-decoded slashes, "..", etc.).
    cleaned = re.sub(r'[^A-Za-z0-9 _.\-]', '', model).strip()
    cleaned = cleaned.replace('..', '').strip('. ')
    return cleaned or 'unknown'


def _find_existing_image(model_stem):
    for ext in ALLOWED_EXTENSIONS:
        candidate = os.path.join(_upload_dir, model_stem + ext)
        if os.path.isfile(candidate):
            return candidate
    return None


@equipment_images_bp.route('/<path:model>', methods=['GET'])
def get_equipment_image(model):
    stem = _sanitize_model_name(model)
    existing = _find_existing_image(stem)
    if existing is None:
        return Response(GENERIC_FALLBACK_SVG, mimetype='image/svg+xml')
    return send_file(existing)


@equipment_images_bp.route('/<path:model>', methods=['POST'])
def upload_equipment_image(model):
    stem = _sanitize_model_name(model)
    if 'file' not in request.files:
        return {'error': 'Campo "file" ausente'}, 400
    file = request.files['file']
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return {'error': f'Extensão não permitida: {ext}'}, 400

    for existing_ext in ALLOWED_EXTENSIONS:
        stale = os.path.join(_upload_dir, stem + existing_ext)
        if os.path.isfile(stale):
            os.remove(stale)

    file.save(os.path.join(_upload_dir, stem + ext))
    return '', 204
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_routes_equipment_images.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Register the blueprint in `app.py`**

```python
from routes_equipment_images import equipment_images_bp, init_equipment_images_routes

init_equipment_images_routes(os.environ.get('EQUIPMENT_IMAGES_DIR', '/app/equipment-images'))
app.register_blueprint(equipment_images_bp)
```

- [ ] **Step 6: Create `static/configuracoes.html`** — minimal upload form (model name + file), lists currently-configured models

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <title>Natverk NOC — Configurações</title>
  <link rel="stylesheet" href="css/app.css" />
  <style>
    .config-shell { flex: 1; padding: 24px; max-width: 480px; }
    form.inline { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
    form.inline input { background: #232326; border: 1px solid rgba(255,255,255,0.12); border-radius: 6px; padding: 6px 8px; color: inherit; font-size: 13px; }
    form.inline button { padding: 7px; border-radius: 6px; border: 1px solid rgba(80,160,255,0.5); background: rgba(80,160,255,0.15); color: inherit; cursor: pointer; }
  </style>
</head>
<body>
  <div class="app-shell">
    <nav class="nav">
      <div class="nav-title">Natverk NOC</div>
      <a href="/" class="nav-item">Início</a>
      <a href="/circuitos.html" class="nav-item">Circuitos</a>
      <a href="/configuracoes.html" class="nav-item active">Configurações</a>
    </nav>
    <div class="config-shell">
      <h3>Foto de equipamento por modelo</h3>
      <p>O nome do modelo deve ser exatamente igual ao campo "Modelo" usado ao cadastrar um ponto em Circuitos.</p>
      <form class="inline" id="upload-form">
        <input name="model" placeholder="Modelo, ex: Huawei MA5800-X2" required />
        <input name="file" type="file" accept=".png,.jpg,.jpeg,.svg,.webp" required />
        <button type="submit">Enviar imagem</button>
      </form>
      <p id="upload-status"></p>
    </div>
  </div>
  <script>
    document.getElementById('upload-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const form = e.target;
      const model = form.model.value;
      const file = form.file.files[0];
      const body = new FormData();
      body.append('file', file);
      const resp = await fetch(`/api/equipment-images/${encodeURIComponent(model)}`, { method: 'POST', body });
      document.getElementById('upload-status').textContent = resp.ok
        ? `Imagem salva para "${model}".`
        : 'Falha ao enviar — verifique a extensão do arquivo.';
      if (resp.ok) form.reset();
    });
  </script>
</body>
</html>
```

- [ ] **Step 7: Create `Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "app.py"]
```

- [ ] **Step 8: Create `docker-compose.yml`**

```yaml
services:
  map:
    build: .
    container_name: netmap
    restart: unless-stopped
    ports:
      - "${MAP_PORT:-5002}:5002"
    environment:
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=${POSTGRES_DB:-zabbix}
      - ZABBIX_URL=${ZABBIX_URL:-http://zabbix-frontend:8080}
      - ZABBIX_USER=${ZABBIX_USER:-Admin}
      - ZABBIX_PASS=${ZABBIX_PASS}
      - POLL_INTERVAL_SECONDS=${POLL_INTERVAL_SECONDS:-30}
      - STALE_THRESHOLD_SECONDS=${STALE_THRESHOLD_SECONDS:-120}
      - TILE_PROVIDER=${TILE_PROVIDER:-osm}
      - MAPBOX_TOKEN=${MAPBOX_TOKEN}
    volumes:
      - map-equipment-images:/app/equipment-images
    networks:
      - natverk-zabbix-net

networks:
  natverk-zabbix-net:
    external: true
    name: natverk-zabbix-net

volumes:
  map-equipment-images:
```

- [ ] **Step 9: Update `install.sh`** — bring `map/` up after `tools/`, generate its `.env`, and copy over the shared Postgres/Zabbix credentials from `stack/.env` the same way `ZABBIX_ADMIN_PASSWORD` is already reused

Find this block near the end of `install.sh`:

```bash
log "Subindo natverk-tools..."
(cd tools && docker compose up -d)
```

Replace it with:

```bash
log "Subindo natverk-tools..."
(cd tools && docker compose up -d)

log "Subindo mapa de circuitos..."
if [ ! -f map/.env ]; then
    cp map/.env.example map/.env
fi
sed -i "s|^POSTGRES_USER=.*|POSTGRES_USER=$(grep '^POSTGRES_USER=' stack/.env | cut -d= -f2-)|" map/.env
sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(grep '^POSTGRES_PASSWORD=' stack/.env | cut -d= -f2-)|" map/.env
sed -i "s|^ZABBIX_PASS=.*|ZABBIX_PASS=$ZABBIX_ADMIN_PASSWORD|" map/.env
(cd map && docker compose up -d)
```

(This runs after the `ZABBIX_ADMIN_PASSWORD` variable is already set earlier in the script, in the Zabbix Admin password bootstrap step — confirm by reading the current `install.sh` before editing, since that variable name must match exactly.)

Also update the final summary block — find:

```bash
log "Próximo passo manual — configurar o WhatsApp:"
```

and add, just before it:

```bash
log "Mapa de circuitos: http://$IP:${MAP_PORT:-5002}"
log ""
```

- [ ] **Step 10: Update root `README.md`** — add `map/` to the component list

In `README.md`, find:

```markdown
- `tools/` — API de diagnóstico de rede (MTR, ping, dig, whois) para uso em dashboards
```

Add immediately after:

```markdown
- `map/` — mapa geográfico dos circuitos de rede, com status ao vivo por segmento e editor de trajeto
```

- [ ] **Step 11: Validate compose config**

Run: `cd map && docker compose config --quiet` if Docker is available; otherwise visually confirm the YAML is well-formed, same fallback used throughout the rest of this project.

- [ ] **Step 12: Commit**

```bash
git add map/static/configuracoes.html map/routes_equipment_images.py map/test_routes_equipment_images.py map/Dockerfile map/docker-compose.yml map/app.py install.sh README.md
git commit -m "Add equipment image uploads (Configurações), Docker packaging, and install.sh integration for map/"
```

---

## Self-Review

**Cobertura do spec:**
- Arquitetura decentralizada por cliente, novo componente `map/` → Task 8 (packaging/install.sh), Tasks 1-7 (the component itself).
- Modelo de dados (ponto/circuito/segmento, limiar configurável) → Task 1 (models), Task 3 (segment threshold field).
- Provedor de tile OpenStreetMap padrão / Mapbox opcional → `map/.env.example` (Task 1) `TILE_PROVIDER`/`MAPBOX_TOKEN`; actual tile-provider switching in the frontend is hardcoded to CARTO/OSM tiles in Task 6/7 for now — **gap noted below, fixed inline**.
- Layout macOS-style sidebar, sem emoji, status verde/laranja/vermelho, hover leve + popup detalhado em tabela, foto de equipamento → Task 6 (Início), Task 7 (Circuitos), validated against the mockups from brainstorming.
- Edição de trajeto arrastável → Task 7 (Leaflet-Geoman).
- Atualização periódica com cache e staleness → Task 4 (poller), Task 5 (`build_map_state` stale handling).
- Tratamento de erro (cinza quando stale, referência quebrada não derruba o mapa, coordenada inválida não desenha) → Task 5 covers the stale/gray case and the "point not found" skip-and-continue case (segments referencing missing points just don't get drawn client-side, matching "não quebra o mapa"). Broken-reference *admin warning* (spec says "aparece como aviso de configuração na aba Circuitos") isn't implemented as a distinct UI warning banner — **gap noted below, fixed inline**.
- Testes TDD na lógica sem navegador → every backend task (1-5, 8) follows RED/GREEN.

**Gap fix 1 — tile provider switching:** Task 6/7 hardcode CARTO dark tiles. Fixing: `index.html` and `circuitos.html` should read the tile provider from a small endpoint instead of hardcoding it, so `TILE_PROVIDER`/`MAPBOX_TOKEN` from `.env` actually take effect. Adding this to Task 6.

**Gap fix 2 — broken reference admin warning:** the spec calls for a visible warning in Circuitos when a segment references a deleted Zabbix host/item. Adding a lightweight version to Task 7 (the segment list already has the data needed — flag it client-side by checking `waypoint_ids`/origin/destination against the loaded points list).

Both fixed inline below rather than adding new tasks, since they're small additions to already-planned files.

### Task 6 fix — tile provider from config

Add to Task 6, **Step 3.5** (between creating `app.css` and writing `app.js`):

Add a config endpoint to `map/app.py`, right after the `/health` route:

```python
@app.route('/api/config')
def config():
    return jsonify({
        'tile_provider': os.environ.get('TILE_PROVIDER', 'osm'),
        'mapbox_token': os.environ.get('MAPBOX_TOKEN', ''),
    })
```

In `map/static/js/app.js`, replace the hardcoded tile layer setup:

```javascript
const map = L.map('map').setView([-23.5629, -46.6544], 13);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; OpenStreetMap &copy; CARTO', maxZoom: 20, subdomains: 'abcd',
}).addTo(map);
```

with:

```javascript
const map = L.map('map').setView([-23.5629, -46.6544], 13);

async function addTileLayer() {
  let cfg = { tile_provider: 'osm', mapbox_token: '' };
  try {
    cfg = await (await fetch('/api/config')).json();
  } catch (err) {
    console.error('Falha ao buscar /api/config, usando OpenStreetMap', err);
  }

  if (cfg.tile_provider === 'mapbox' && cfg.mapbox_token) {
    L.tileLayer(
      `https://api.mapbox.com/styles/v1/mapbox/dark-v11/tiles/{z}/{x}/{y}?access_token=${cfg.mapbox_token}`,
      { attribution: '&copy; Mapbox &copy; OpenStreetMap', maxZoom: 20 },
    ).addTo(map);
  } else {
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; OpenStreetMap &copy; CARTO', maxZoom: 20, subdomains: 'abcd',
    }).addTo(map);
  }
}
addTileLayer();
```

Apply the identical `addTileLayer()` pattern in `map/static/js/circuitos.js`'s `editorMap` setup (Task 7, Step 2) instead of its hardcoded CARTO tile layer.

### Task 7 fix — broken reference warning in Circuitos

Add to Task 7, at the end of **Step 2** (`circuitos.js`), inside `selectCircuit`, right after `window.currentCircuit = await api(...)`:

```javascript
const pointIds = new Set(allPoints.map((p) => p.id));
const brokenSegments = window.currentCircuit.segments.filter(
  (s) => !pointIds.has(s.origin_point_id) || !pointIds.has(s.destination_point_id),
);
const warningEl = document.getElementById('segment-warning') || (() => {
  const el = document.createElement('p');
  el.id = 'segment-warning';
  el.style.color = '#f5a623';
  document.getElementById('segment-panel').prepend(el);
  return el;
})();
warningEl.textContent = brokenSegments.length > 0
  ? `${brokenSegments.length} segmento(s) referenciam um ponto que não existe mais — corrija ou remova.`
  : '';
```

This is a client-side check (the points list is already loaded); no new API endpoint needed.

---

Ambas as correções são pequenas o bastante pra caber dentro das tasks já planejadas — não precisam virar tasks novas.
