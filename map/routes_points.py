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
