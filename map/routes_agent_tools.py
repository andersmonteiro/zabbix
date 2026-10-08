"""Endpoints que o agente de IA central chama (nunca o navegador) pra
consultar o que o Zabbix não cobre. Protegidos por um token compartilhado
próprio (AGENT_TOOLS_TOKEN), separado do login de sessão usado pelo resto
do app -- o agente central não tem cookie de sessão, só esse bearer token.
"""
import os

from flask import Blueprint, jsonify, request

from models import InterfaceCache, Point, RouteCache
from ssh_tools import SSHToolError, get_bgp_prefixes, get_device_logs

agent_tools_bp = Blueprint('agent_tools', __name__, url_prefix='/api/agent-tools')

_zabbix_client = None
_session_factory = None


def init_agent_tools_routes(zabbix_client, session_factory):
    global _zabbix_client, _session_factory
    _zabbix_client = zabbix_client
    _session_factory = session_factory


@agent_tools_bp.before_request
def _require_agent_token():
    expected = os.environ.get('AGENT_TOOLS_TOKEN')
    if not expected:
        return jsonify({'error': 'AGENT_TOOLS_TOKEN não configurado nesta VM'}), 503
    got = (request.headers.get('Authorization') or '').removeprefix('Bearer ').strip()
    if got != expected:
        return jsonify({'error': 'Token inválido'}), 401


@agent_tools_bp.route('/interfaces/<hostid>', methods=['GET'])
def interfaces(hostid):
    """IP e descrição de cada interface, + sinal óptico quando o
    equipamento tem SFP -- vem do cache (atualizado a cada alguns minutos
    pelo ssh_poller), nunca de uma conexão SSH ao vivo."""
    session = _session_factory()
    try:
        point = session.query(Point).filter_by(zabbix_hostid=hostid).first()
        if point is None:
            return jsonify([])
        rows = session.query(InterfaceCache).filter_by(point_id=point.id).all()
        return jsonify([
            {
                'interface': r.interface_name,
                'ip_address': r.ip_address,
                'description': r.description,
                'optical_rx_dbm': r.optical_rx_dbm,
                'optical_tx_dbm': r.optical_tx_dbm,
                'updated_at': r.updated_at.isoformat(),
            }
            for r in rows
        ])
    finally:
        session.close()


@agent_tools_bp.route('/routes/<hostid>', methods=['GET'])
def routes(hostid):
    """Rotas estáticas cadastradas no host -- também vem do cache."""
    session = _session_factory()
    try:
        point = session.query(Point).filter_by(zabbix_hostid=hostid).first()
        if point is None:
            return jsonify([])
        rows = session.query(RouteCache).filter_by(point_id=point.id).all()
        return jsonify([
            {
                'destination': r.destination,
                'next_hop': r.next_hop,
                'interface': r.interface_name,
                'updated_at': r.updated_at.isoformat(),
            }
            for r in rows
        ])
    finally:
        session.close()


@agent_tools_bp.route('/bgp-prefixes', methods=['POST'])
def bgp_prefixes():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora."""
    data = request.get_json(force=True, silent=True) or {}
    hostid, neighbor_ip = data.get('hostid'), data.get('neighbor_ip')
    if not hostid or not neighbor_ip:
        return jsonify({'error': 'hostid e neighbor_ip são obrigatórios'}), 400
    try:
        output = get_bgp_prefixes(hostid, neighbor_ip, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/device-logs', methods=['POST'])
def device_logs():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora."""
    data = request.get_json(force=True, silent=True) or {}
    hostid, since = data.get('hostid'), data.get('since')
    if not hostid:
        return jsonify({'error': 'hostid é obrigatório'}), 400
    try:
        output = get_device_logs(hostid, since, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502
