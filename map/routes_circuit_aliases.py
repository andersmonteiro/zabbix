from flask import Blueprint, jsonify, request

from models import CircuitAlias, Point

circuit_aliases_bp = Blueprint('circuit_aliases', __name__, url_prefix='/api/circuit-aliases')

_session_factory = None


def init_circuit_aliases_routes(session_factory):
    global _session_factory
    _session_factory = session_factory


def _serialize(alias, db):
    point = db.query(Point).filter(Point.zabbix_hostid == alias.zabbix_hostid).first()
    return {
        'id': alias.id,
        'alias': alias.alias,
        'hostid': alias.zabbix_hostid,
        'host_name': point.name if point is not None else None,
        'interface': alias.interface_name,
        'note': alias.note,
        'created_at': alias.created_at.isoformat(),
    }


@circuit_aliases_bp.route('', methods=['GET'])
def list_circuit_aliases():
    db = _session_factory()
    try:
        aliases = db.query(CircuitAlias).order_by(CircuitAlias.alias).all()
        return jsonify([_serialize(a, db) for a in aliases])
    finally:
        db.close()


@circuit_aliases_bp.route('', methods=['POST'])
def create_circuit_alias():
    data = request.get_json(force=True, silent=True) or {}
    alias = (data.get('alias') or '').strip()
    hostid = (data.get('hostid') or '').strip()
    interface = (data.get('interface') or '').strip()
    note = (data.get('note') or '').strip()
    if not alias or not hostid or not interface:
        return jsonify({'error': 'alias, hostid e interface são obrigatórios'}), 400

    db = _session_factory()
    try:
        row = CircuitAlias(alias=alias, zabbix_hostid=hostid, interface_name=interface, note=note or None)
        db.add(row)
        db.commit()
        return jsonify(_serialize(row, db)), 201
    finally:
        db.close()


@circuit_aliases_bp.route('/<int:alias_id>', methods=['DELETE'])
def delete_circuit_alias(alias_id):
    db = _session_factory()
    try:
        row = db.get(CircuitAlias, alias_id)
        if row is None:
            return jsonify({'error': 'Apelido não encontrado'}), 404
        db.delete(row)
        db.commit()
        return '', 204
    finally:
        db.close()
