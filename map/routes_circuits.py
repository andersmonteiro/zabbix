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
        'port_name': segment.port_name,
        'zabbix_speed_itemid': segment.zabbix_speed_itemid,
        'zabbix_throughput_in_itemid': segment.zabbix_throughput_in_itemid,
        'zabbix_throughput_out_itemid': segment.zabbix_throughput_out_itemid,
        'zabbix_optical_rx_itemid': segment.zabbix_optical_rx_itemid,
        'zabbix_optical_tx_itemid': segment.zabbix_optical_tx_itemid,
        'zabbix_error_itemid': segment.zabbix_error_itemid,
        'zabbix_operstatus_itemid': segment.zabbix_operstatus_itemid,
        'zabbix_snmp_available_itemid': segment.zabbix_snmp_available_itemid,
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
    'waypoint_ids', 'port_name', 'zabbix_speed_itemid', 'zabbix_throughput_in_itemid',
    'zabbix_throughput_out_itemid', 'zabbix_optical_rx_itemid', 'zabbix_optical_tx_itemid',
    'zabbix_error_itemid', 'zabbix_operstatus_itemid', 'zabbix_snmp_available_itemid',
    'signal_warn_threshold_dbm',
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
            port_name=data.get('port_name'),
            zabbix_speed_itemid=data.get('zabbix_speed_itemid'),
            zabbix_throughput_in_itemid=data.get('zabbix_throughput_in_itemid'),
            zabbix_throughput_out_itemid=data.get('zabbix_throughput_out_itemid'),
            zabbix_optical_rx_itemid=data.get('zabbix_optical_rx_itemid'),
            zabbix_optical_tx_itemid=data.get('zabbix_optical_tx_itemid'),
            zabbix_error_itemid=data.get('zabbix_error_itemid'),
            zabbix_operstatus_itemid=data.get('zabbix_operstatus_itemid'),
            zabbix_snmp_available_itemid=data.get('zabbix_snmp_available_itemid'),
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
