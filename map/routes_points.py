from flask import Blueprint, jsonify, request
from sqlalchemy import or_

from models import Point, Segment

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
        'zabbix_snmp_available_itemid': point.zabbix_snmp_available_itemid,
        'zabbix_uptime_itemid': point.zabbix_uptime_itemid,
        'equipment_model': point.equipment_model,
        'equipment_ip': point.equipment_ip,
    }


REQUIRED_FIELDS = ('name', 'lat', 'lng', 'point_type')

COORDINATE_RANGES = {'lat': (-90.0, 90.0), 'lng': (-180.0, 180.0)}


def _coerce_coordinate(field, value):
    """Returns (float_value, None) or (None, error_message).

    The presence check alone is not enough: the frontend sends
    `parseFloat(input.value)`, and a non-numeric input becomes NaN, which
    JSON.stringify serializes as null. The key is present, so the required-field
    check passes, and `lat=None` against a nullable=False column used to blow up
    as an unhandled IntegrityError -> 500.
    """
    low, high = COORDINATE_RANGES[field]
    if value is None or isinstance(value, bool):
        return None, f'{field} deve ser um número entre {low:g} e {high:g}'
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, f'{field} deve ser um número entre {low:g} e {high:g}'
    if number != number:  # NaN
        return None, f'{field} deve ser um número entre {low:g} e {high:g}'
    if not (low <= number <= high):
        return None, f'{field} fora do intervalo válido ({low:g} a {high:g})'
    return number, None


def _validate_coordinates(data):
    """Validates whichever of lat/lng are present. Returns (values, error)."""
    values = {}
    for field in ('lat', 'lng'):
        if field not in data:
            continue
        number, error = _coerce_coordinate(field, data[field])
        if error is not None:
            return None, error
        values[field] = number
    return values, None


def _segments_referencing(session, point_id):
    """Every segment that would be left with a dangling reference if this point
    were deleted. `waypoint_ids` is a JSON column, so it is filtered in Python
    to stay portable across SQLite (tests) and Postgres (production)."""
    referencing = session.query(Segment).filter(or_(
        Segment.origin_point_id == point_id,
        Segment.destination_point_id == point_id,
    )).all()
    seen = {segment.id for segment in referencing}
    for segment in session.query(Segment).all():
        if segment.id not in seen and point_id in (segment.waypoint_ids or []):
            referencing.append(segment)
    return referencing


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
    if data['point_type'] not in ('waypoint', 'equipment', 'route_point'):
        return jsonify({'error': "point_type deve ser 'waypoint', 'equipment' ou 'route_point'"}), 400

    coordinates, error = _validate_coordinates(data)
    if error is not None:
        return jsonify({'error': error}), 400

    session = _session_factory()
    try:
        point = Point(
            name=data['name'], lat=coordinates['lat'], lng=coordinates['lng'],
            point_type=data['point_type'],
            zabbix_hostid=data.get('zabbix_hostid'),
            zabbix_status_itemid=data.get('zabbix_status_itemid'),
            zabbix_cpu_itemid=data.get('zabbix_cpu_itemid'),
            zabbix_snmp_available_itemid=data.get('zabbix_snmp_available_itemid'),
            zabbix_uptime_itemid=data.get('zabbix_uptime_itemid'),
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
    coordinates, error = _validate_coordinates(data)
    if error is not None:
        return jsonify({'error': error}), 400

    session = _session_factory()
    try:
        point = session.get(Point, point_id)
        if point is None:
            return jsonify({'error': 'Ponto não encontrado'}), 404
        for field in (
            'name', 'lat', 'lng', 'point_type', 'zabbix_hostid',
            'zabbix_status_itemid', 'zabbix_cpu_itemid', 'zabbix_snmp_available_itemid',
            'zabbix_uptime_itemid', 'equipment_model', 'equipment_ip',
        ):
            if field in data:
                setattr(point, field, coordinates.get(field, data[field]))
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

        # SQLite does not enforce foreign keys by default, so a bare delete
        # would look fine in tests while dangling the reference; on Postgres
        # the same delete raises IntegrityError -> unhandled 500. Refuse it.
        referencing = _segments_referencing(session, point_id)
        if referencing:
            return jsonify({'error': (
                f'Não é possível remover: ponto usado por {len(referencing)} segmento(s)'
            )}), 409

        session.delete(point)
        session.commit()
        return '', 204
    finally:
        session.close()
