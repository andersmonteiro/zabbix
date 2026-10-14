"""Endpoints que o agente de IA central chama (nunca o navegador) pra
consultar o que o Zabbix não cobre. Protegidos por um token compartilhado
próprio (AGENT_TOOLS_TOKEN), separado do login de sessão usado pelo resto
do app -- o agente central não tem cookie de sessão, só esse bearer token.
"""
import hmac
import os
import re

from flask import Blueprint, jsonify, request

from models import CircuitAlias, InterfaceCache, Point, RouteCache, User
from ssh_tools import (
    SSHToolError,
    get_bgp_config,
    get_bgp_peer_detail,
    get_bgp_peers,
    get_bgp_prefixes,
    get_device_logs,
    get_full_config,
    get_host_functions,
    get_interface_arp,
    get_interface_config,
    get_interface_status,
    get_ip_prefix_list,
    get_mac_address_by_vlan,
    get_ipv6_prefix_list,
    get_pppoe_aaa_fail_record,
    get_pppoe_pool_usage,
    get_pppoe_session_by_username,
    get_pppoe_session_by_vlan,
    get_pppoe_sessions,
    get_pppoe_summary,
    get_route_policy_config,
    get_route_to_destination,
    get_vlan_summary,
)

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
    if not hmac.compare_digest(got, expected):
        return jsonify({'error': 'Token inválido'}), 401


def _cache_miss_note(point):
    """Uma lista vazia sozinha é ambígua pro agente: "sem dado ainda" e
    "esse host realmente não tem nada disso" ficam indistinguíveis, e sem
    isso o modelo depende só da instrução geral de "não inventar" pra não
    concluir a coisa errada. Devolver esse aviso junto da lista reforça
    explicitamente qual dos dois casos é, pro agente nunca precisar
    adivinhar -- não muda nada quando o cache tem dado de verdade."""
    if point is None:
        return 'Host sem Point associado no map/ -- nunca foi processado pelo poller de cache SSH, sem dado disponível ainda.'
    return (
        'Point existe mas o cache está vazio -- o poller pode não ter rodado '
        'com sucesso ainda pra esse host, ou esse fabricante não tem suporte '
        'a essa consulta implementado.'
    )


@agent_tools_bp.route('/interfaces/<hostid>', methods=['GET'])
def interfaces(hostid):
    """IP e descrição de cada interface, + sinal óptico quando o
    equipamento tem SFP -- vem do cache (atualizado a cada alguns minutos
    pelo ssh_poller), nunca de uma conexão SSH ao vivo."""
    session = _session_factory()
    try:
        point = session.query(Point).filter_by(zabbix_hostid=hostid).first()
        rows = session.query(InterfaceCache).filter_by(point_id=point.id).all() if point is not None else []
        result = {
            'interfaces': [
                {
                    'interface': r.interface_name,
                    'ip_address': r.ip_address,
                    'description': r.description,
                    'optical_rx_dbm': r.optical_rx_dbm,
                    'optical_tx_dbm': r.optical_tx_dbm,
                    'updated_at': r.updated_at.isoformat(),
                }
                for r in rows
            ],
        }
        if not rows:
            result['note'] = _cache_miss_note(point)
        return jsonify(result)
    finally:
        session.close()


@agent_tools_bp.route('/routes/<hostid>', methods=['GET'])
def routes(hostid):
    """Rotas estáticas cadastradas no host -- também vem do cache."""
    session = _session_factory()
    try:
        point = session.query(Point).filter_by(zabbix_hostid=hostid).first()
        rows = session.query(RouteCache).filter_by(point_id=point.id).all() if point is not None else []
        result = {
            'routes': [
                {
                    'destination': r.destination,
                    'next_hop': r.next_hop,
                    'interface': r.interface_name,
                    'updated_at': r.updated_at.isoformat(),
                }
                for r in rows
            ],
        }
        if not rows:
            result['note'] = _cache_miss_note(point)
        return jsonify(result)
    finally:
        session.close()


@agent_tools_bp.route('/host-functions/<hostid>', methods=['GET'])
def host_functions(hostid):
    """Não abre SSH -- só lê o cadastro de macros do Zabbix. Serve pra
    desambiguar qual host usar quando a busca por nome trouxer mais de um
    candidato."""
    try:
        return jsonify({'functions': get_host_functions(hostid, _zabbix_client)})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/search-interfaces', methods=['POST'])
def search_interfaces():
    """Não abre SSH -- busca por trecho da DESCRIÇÃO de interface em TODOS
    os hosts já cacheados de uma vez, sem precisar saber de antemão em
    qual host/local está. Serve pro caso real de cliente/NOC descrevendo
    um circuito pelo apelido dele (ex: "fibra da travessia", "link do
    PE-tal") sem dizer o host -- o apelido normalmente bate com a
    descrição cadastrada na porta em um ou mais equipamentos (ex: os dois
    lados de uma travessia de fibra, cada um num switch diferente).

    Primeiro checa os apelidos cadastrados manualmente (CircuitAlias,
    ver /admin/circuit-aliases) -- resolução exata, o operador que
    ensinou. Só cai pra busca por trecho de descrição (cache de
    interfaces) quando nenhum apelido bate: a lista de apelidos cresce
    aos poucos, conforme casos reais vão sendo cadastrados."""
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get('query') or '').strip()
    if not query:
        return jsonify({'error': 'query é obrigatório'}), 400
    session = _session_factory()
    try:
        alias_rows = (
            session.query(CircuitAlias, Point)
            .join(Point, CircuitAlias.zabbix_hostid == Point.zabbix_hostid)
            .filter(CircuitAlias.alias.ilike(f'%{query}%'))
            .all()
        )
        if alias_rows:
            return jsonify({
                'matches': [
                    {
                        'hostid': point.zabbix_hostid,
                        'host_name': point.name,
                        'interface': alias.interface_name,
                        'description': f'Apelido cadastrado: "{alias.alias}"' + (f' -- {alias.note}' if alias.note else ''),
                    }
                    for alias, point in alias_rows
                ],
            })

        rows = (
            session.query(InterfaceCache, Point)
            .join(Point, InterfaceCache.point_id == Point.id)
            .filter(InterfaceCache.description.ilike(f'%{query}%'))
            .all()
        )
        return jsonify({
            'matches': [
                {
                    'hostid': point.zabbix_hostid,
                    'host_name': point.name,
                    'interface': iface.interface_name,
                    'description': iface.description,
                }
                for iface, point in rows
            ],
        })
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


@agent_tools_bp.route('/bgp-peers', methods=['POST'])
def bgp_peers():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora. Lista
    TODAS as sessões BGP (nome do peer é o próprio IP, estado, tempo de
    atividade) -- use pra achar o vizinho certo quando não se sabe de
    antemão o IP dele."""
    data = request.get_json(force=True, silent=True) or {}
    hostid = data.get('hostid')
    if not hostid:
        return jsonify({'error': 'hostid é obrigatório'}), 400
    try:
        output = get_bgp_peers(hostid, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/bgp-peer-detail', methods=['POST'])
def bgp_peer_detail():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora."""
    data = request.get_json(force=True, silent=True) or {}
    hostid, peer_ip = data.get('hostid'), data.get('peer_ip')
    if not hostid or not peer_ip:
        return jsonify({'error': 'hostid e peer_ip são obrigatórios'}), 400
    try:
        output = get_bgp_peer_detail(hostid, peer_ip, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/bgp-config', methods=['POST'])
def bgp_config():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora."""
    data = request.get_json(force=True, silent=True) or {}
    hostid = data.get('hostid')
    if not hostid:
        return jsonify({'error': 'hostid é obrigatório'}), 400
    try:
        output = get_bgp_config(hostid, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/route-policy-config', methods=['POST'])
def route_policy_config():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora."""
    data = request.get_json(force=True, silent=True) or {}
    hostid = data.get('hostid')
    if not hostid:
        return jsonify({'error': 'hostid é obrigatório'}), 400
    try:
        output = get_route_policy_config(hostid, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/ip-prefix-list', methods=['POST'])
def ip_prefix_list():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora."""
    data = request.get_json(force=True, silent=True) or {}
    hostid = data.get('hostid')
    if not hostid:
        return jsonify({'error': 'hostid é obrigatório'}), 400
    try:
        output = get_ip_prefix_list(hostid, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/ipv6-prefix-list', methods=['POST'])
def ipv6_prefix_list():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora."""
    data = request.get_json(force=True, silent=True) or {}
    hostid = data.get('hostid')
    if not hostid:
        return jsonify({'error': 'hostid é obrigatório'}), 400
    try:
        output = get_ipv6_prefix_list(hostid, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/pppoe-summary', methods=['POST'])
def pppoe_summary():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora. Total
    consolidado de assinantes PPPoE conectados."""
    data = request.get_json(force=True, silent=True) or {}
    hostid = data.get('hostid')
    if not hostid:
        return jsonify({'error': 'hostid é obrigatório'}), 400
    try:
        output = get_pppoe_summary(hostid, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/pppoe-sessions', methods=['POST'])
def pppoe_sessions():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora. Lista
    completa de sessões PPPoE (pode ser longa)."""
    data = request.get_json(force=True, silent=True) or {}
    hostid = data.get('hostid')
    if not hostid:
        return jsonify({'error': 'hostid é obrigatório'}), 400
    try:
        output = get_pppoe_sessions(hostid, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/pppoe-session-by-vlan', methods=['POST'])
def pppoe_session_by_vlan():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora."""
    data = request.get_json(force=True, silent=True) or {}
    hostid, pevlan = data.get('hostid'), data.get('pevlan')
    if not hostid or not pevlan:
        return jsonify({'error': 'hostid e pevlan são obrigatórios'}), 400
    try:
        output = get_pppoe_session_by_vlan(hostid, pevlan, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/pppoe-session-by-username', methods=['POST'])
def pppoe_session_by_username():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora."""
    data = request.get_json(force=True, silent=True) or {}
    hostid, username_fragment = data.get('hostid'), data.get('username_fragment')
    if not hostid or not username_fragment:
        return jsonify({'error': 'hostid e username_fragment são obrigatórios'}), 400
    try:
        output = get_pppoe_session_by_username(hostid, username_fragment, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/pppoe-pool-usage', methods=['POST'])
def pppoe_pool_usage():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora."""
    data = request.get_json(force=True, silent=True) or {}
    hostid = data.get('hostid')
    if not hostid:
        return jsonify({'error': 'hostid é obrigatório'}), 400
    try:
        output = get_pppoe_pool_usage(hostid, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/pppoe-aaa-fail-record', methods=['POST'])
def pppoe_aaa_fail_record():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora."""
    data = request.get_json(force=True, silent=True) or {}
    hostid, pevlan = data.get('hostid'), data.get('pevlan')
    if not hostid or not pevlan:
        return jsonify({'error': 'hostid e pevlan são obrigatórios'}), 400
    try:
        output = get_pppoe_aaa_fail_record(hostid, pevlan, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/interface-status', methods=['POST'])
def interface_status():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora."""
    data = request.get_json(force=True, silent=True) or {}
    hostid, interface = data.get('hostid'), data.get('interface')
    if not hostid or not interface:
        return jsonify({'error': 'hostid e interface são obrigatórios'}), 400
    try:
        output = get_interface_status(hostid, interface, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/mac-address-by-vlan', methods=['POST'])
def mac_address_by_vlan():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora."""
    data = request.get_json(force=True, silent=True) or {}
    hostid, vlan_id = data.get('hostid'), data.get('vlan_id')
    if not hostid or not vlan_id:
        return jsonify({'error': 'hostid e vlan_id são obrigatórios'}), 400
    try:
        output = get_mac_address_by_vlan(hostid, vlan_id, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/vlan-summary', methods=['POST'])
def vlan_summary():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora."""
    data = request.get_json(force=True, silent=True) or {}
    hostid = data.get('hostid')
    if not hostid:
        return jsonify({'error': 'hostid é obrigatório'}), 400
    try:
        output = get_vlan_summary(hostid, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/full-config', methods=['POST'])
def full_config():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora. Saída
    pode ser bem longa."""
    data = request.get_json(force=True, silent=True) or {}
    hostid = data.get('hostid')
    if not hostid:
        return jsonify({'error': 'hostid é obrigatório'}), 400
    try:
        output = get_full_config(hostid, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/route-lookup', methods=['POST'])
def route_lookup():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora. Rota de
    melhor match pra um IP específico, de qualquer protocolo (não só
    estática)."""
    data = request.get_json(force=True, silent=True) or {}
    hostid, destination = data.get('hostid'), data.get('destination')
    if not hostid or not destination:
        return jsonify({'error': 'hostid e destination são obrigatórios'}), 400
    try:
        output = get_route_to_destination(hostid, destination, _zabbix_client)
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


@agent_tools_bp.route('/interface-config', methods=['POST'])
def interface_config():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora. Traz
    TODOS os IPs/sub-IPs configurados na interface, diferente do cache
    de /interfaces (que só tem o IP principal)."""
    data = request.get_json(force=True, silent=True) or {}
    hostid, interface = data.get('hostid'), data.get('interface')
    if not hostid or not interface:
        return jsonify({'error': 'hostid e interface são obrigatórios'}), 400
    try:
        output = get_interface_config(hostid, interface, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


@agent_tools_bp.route('/interface-arp', methods=['POST'])
def interface_arp():
    """Estado ao vivo -- nunca cacheado, sempre abre SSH na hora."""
    data = request.get_json(force=True, silent=True) or {}
    hostid, interface = data.get('hostid'), data.get('interface')
    if not hostid or not interface:
        return jsonify({'error': 'hostid e interface são obrigatórios'}), 400
    try:
        output = get_interface_arp(hostid, interface, _zabbix_client)
        return jsonify({'output': output})
    except SSHToolError as e:
        return jsonify({'error': str(e)}), 502


def _normalize_digits(value):
    return re.sub(r'\D', '', value or '')


@agent_tools_bp.route('/user-by-phone/<phone>', methods=['GET'])
def user_by_phone(phone):
    """Pro agente saber o nome de quem está chamando via WhatsApp --
    compara só os dígitos, por sufixo (o telefone cadastrado no usuário
    pode ou não ter o código do país, tanto faz quem está perguntando).
    Sem usuário encontrado: 200 com display_name=None (não é erro, é
    esperado pra qualquer número que ainda não tem conta vinculada)."""
    phone_digits = _normalize_digits(phone)
    if not phone_digits:
        return jsonify({'display_name': None})
    session = _session_factory()
    try:
        for user in session.query(User).filter(User.phone_number.isnot(None)):
            user_digits = _normalize_digits(user.phone_number)
            if user_digits and phone_digits.endswith(user_digits):
                return jsonify({'display_name': user.display_name or user.username})
        return jsonify({'display_name': None})
    finally:
        session.close()
