"""Consulta direta via SSH ao equipamento -- só o que o Zabbix não coleta
(sinal óptico, prefixos BGP, IP de VLAN, log do equipamento). Credenciais
vêm das macros do host no Zabbix ({$SSH_USER}/{$SSH_PASS}/{$SSH_PORT}),
nunca duplicadas em outro lugar. Só comandos de leitura -- nenhuma função
aqui jamais compõe texto de comando a partir de entrada livre do modelo;
cada capacidade tem seu comando fixo por fabricante, testado manualmente.

Os parsers de texto (_parse_huawei_*/_parse_mikrotik_*) são um ponto de
partida baseado no formato documentado de cada comando -- IGUAL ao
catálogo de ferramentas Zabbix do projeto, cada um precisa ser validado
contra a saída real de um equipamento antes de confiar cegamente neles.
"""
import logging
import re

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

from zabbix_client import ZabbixAPIError

logger = logging.getLogger(__name__)

# {$VENDOR} no Zabbix -> device_type do netmiko.
_NETMIKO_DEVICE_TYPE = {
    'huawei': 'huawei',
    'mikrotik': 'mikrotik_routeros',
}

CONNECT_TIMEOUT = 8


class SSHToolError(Exception):
    """Erro conhecido (sem credencial, fabricante não suportado, falha de
    conexão) -- sempre com mensagem segura pra mostrar ao usuário/modelo."""


def _fetch_host_info(hostid, zabbix_client):
    try:
        hosts = zabbix_client.call('host.get', {
            'hostids': [hostid],
            'output': ['hostid', 'host'],
            'selectInterfaces': ['ip'],
            'selectMacros': ['macro', 'value'],
        })
    except ZabbixAPIError as e:
        raise SSHToolError(f'Falha ao consultar o Zabbix: {e}') from e
    if not hosts:
        raise SSHToolError(f'Host {hostid} não encontrado no Zabbix')

    host = hosts[0]
    macros = {m['macro']: m['value'] for m in host.get('macros', [])}
    ifaces = host.get('interfaces') or []

    vendor = (macros.get('{$VENDOR}') or '').strip().lower()
    ip = ifaces[0]['ip'] if ifaces else None
    ssh_user = macros.get('{$SSH_USER}')
    ssh_pass = macros.get('{$SSH_PASS}')
    ssh_port = macros.get('{$SSH_PORT}') or '22'

    if not ip:
        raise SSHToolError(f'Host {host["host"]} não tem IP cadastrado')
    if vendor not in _NETMIKO_DEVICE_TYPE:
        raise SSHToolError(
            f'Fabricante "{vendor or "não definido"}" não suportado via SSH '
            '(só Huawei e Mikrotik por enquanto)'
        )
    if not ssh_user or not ssh_pass:
        raise SSHToolError(f'Host {host["host"]} não tem credencial SSH cadastrada')

    return {
        'name': host['host'],
        'vendor': vendor,
        'device_type': _NETMIKO_DEVICE_TYPE[vendor],
        'ip': ip,
        'port': int(ssh_port),
        'username': ssh_user,
        'password': ssh_pass,
    }


def _connect(info):
    try:
        return ConnectHandler(
            device_type=info['device_type'],
            host=info['ip'],
            port=info['port'],
            username=info['username'],
            password=info['password'],
            timeout=CONNECT_TIMEOUT,
            banner_timeout=CONNECT_TIMEOUT,
            auth_timeout=CONNECT_TIMEOUT,
        )
    except NetmikoAuthenticationException as e:
        raise SSHToolError(f'Usuário/senha SSH recusados por {info["ip"]}') from e
    except NetmikoTimeoutException as e:
        raise SSHToolError(f'Não respondeu na porta SSH ({info["ip"]}:{info["port"]})') from e
    except Exception as e:
        raise SSHToolError(f'Falha ao conectar em {info["ip"]}: {e}') from e


def test_ssh(hostid, zabbix_client):
    """Abre e fecha uma conexão, sem rodar comando nenhum -- só confirma
    que login funciona. Usado pelo botão "Testar SSH" na tela de Hosts."""
    info = _fetch_host_info(hostid, zabbix_client)
    conn = _connect(info)
    conn.disconnect()
    return f'Conectado em {info["name"]} ({info["ip"]}) como {info["username"]}'


def get_optical_signal(hostid, port, zabbix_client):
    info = _fetch_host_info(hostid, zabbix_client)
    conn = _connect(info)
    try:
        if info['vendor'] == 'huawei':
            output = conn.send_command(f'display interface {port} optical-info')
        else:
            output = conn.send_command(f'/interface ethernet monitor {port} once')
        return output
    finally:
        conn.disconnect()


def get_bgp_prefixes(hostid, neighbor_ip, zabbix_client):
    info = _fetch_host_info(hostid, zabbix_client)
    conn = _connect(info)
    try:
        if info['vendor'] == 'huawei':
            output = conn.send_command(
                f'display bgp routing-table peer {neighbor_ip} advertised-routes'
            )
        else:
            output = conn.send_command(
                f'/routing bgp advertisements print peer={neighbor_ip}'
            )
        return output
    finally:
        conn.disconnect()


def get_vlan_ip(hostid, vlan_id, zabbix_client):
    info = _fetch_host_info(hostid, zabbix_client)
    conn = _connect(info)
    try:
        if info['vendor'] == 'huawei':
            output = conn.send_command(f'display interface Vlanif{vlan_id}')
        else:
            output = conn.send_command(f'/ip address print where interface=vlan{vlan_id}')
        return output
    finally:
        conn.disconnect()


def get_device_logs(hostid, since, zabbix_client):
    """`since` é uma data/hora em texto já no formato que o próprio
    equipamento espera (ex: '2026-10-08') -- validado como uma string
    comum, nunca interpolado dentro de um comando montado livremente."""
    info = _fetch_host_info(hostid, zabbix_client)
    conn = _connect(info)
    try:
        if info['vendor'] == 'huawei':
            output = conn.send_command('display logbuffer')
        else:
            output = conn.send_command(f'/log print where time>={since}')
        return output
    finally:
        conn.disconnect()


# ── Cache periódico (interfaces + rotas estáticas) ──────────────────────

_HUAWEI_BRIEF_RE = re.compile(
    r'^(?P<name>\S+)\s+(?P<ip>\S+)\s+(?:up|down|\*down|\^down)\s+(?:up|down)\s*$',
    re.MULTILINE,
)
_HUAWEI_DESC_RE = re.compile(
    r'^(?P<name>\S+)\s+(?:up|down|\*down|\^down|--)\s+(?:up|down|--)\s+(?P<desc>\S.*)$',
    re.MULTILINE,
)
_HUAWEI_OPTICAL_RE = re.compile(
    r'(?:Rx|RX)[^:\n]*power[^:\n]*:\s*(?P<rx>-?\d+\.?\d*).*?'
    r'(?:Tx|TX)[^:\n]*power[^:\n]*:\s*(?P<tx>-?\d+\.?\d*)',
    re.IGNORECASE | re.DOTALL,
)
_HUAWEI_STATIC_ROUTE_RE = re.compile(
    r'^(?P<dest>\d+\.\d+\.\d+\.\d+/\d+)\s+Static\s+\d+\s+\d+\s+\S+\s+(?P<nexthop>\S+)\s+(?P<iface>\S+)\s*$',
    re.MULTILINE,
)

_MIKROTIK_ADDRESS_RE = re.compile(
    r'^\s*\d+\s+[DX ]*\s*(?P<ip>\d+\.\d+\.\d+\.\d+/\d+)\s+\S+\s+(?P<iface>\S+)\s*$',
    re.MULTILINE,
)
_MIKROTIK_COMMENT_RE = re.compile(
    r'name="?(?P<name>[\w\-/]+)"?.*?comment="(?P<desc>[^"]*)"',
    re.DOTALL,
)
_MIKROTIK_OPTICAL_RE = re.compile(
    r'rx-power:\s*(?P<rx>-?\d+\.?\d*).*?tx-power:\s*(?P<tx>-?\d+\.?\d*)',
    re.IGNORECASE | re.DOTALL,
)
_MIKROTIK_ROUTE_RE = re.compile(
    r'dst-address=(?P<dest>\S+).*?gateway=(?P<nexthop>\S+)',
)


def _parse_huawei_interfaces(brief_output, desc_output):
    ifaces = {}
    for m in _HUAWEI_BRIEF_RE.finditer(brief_output):
        name = m.group('name')
        ip = m.group('ip')
        ifaces[name] = {'ip_address': None if ip.lower() == 'unassigned' else ip, 'description': None}
    for m in _HUAWEI_DESC_RE.finditer(desc_output):
        name = m.group('name')
        if name in ifaces:
            ifaces[name]['description'] = m.group('desc').strip() or None
    return ifaces


def _parse_optical(output, vendor):
    pattern = _HUAWEI_OPTICAL_RE if vendor == 'huawei' else _MIKROTIK_OPTICAL_RE
    m = pattern.search(output)
    if not m:
        return None, None
    try:
        return float(m.group('rx')), float(m.group('tx'))
    except (TypeError, ValueError):
        return None, None


def _parse_huawei_routes(output):
    return [
        {'destination': m.group('dest'), 'next_hop': m.group('nexthop'), 'interface_name': m.group('iface')}
        for m in _HUAWEI_STATIC_ROUTE_RE.finditer(output)
    ]


def _parse_mikrotik_interfaces(address_output, interface_detail_output):
    ifaces = {}
    for m in _MIKROTIK_ADDRESS_RE.finditer(address_output):
        name = m.group('iface')
        ifaces[name] = {'ip_address': m.group('ip'), 'description': None}
    for m in _MIKROTIK_COMMENT_RE.finditer(interface_detail_output):
        name = m.group('name')
        if name in ifaces:
            ifaces[name]['description'] = m.group('desc').strip() or None
        else:
            ifaces[name] = {'ip_address': None, 'description': m.group('desc').strip() or None}
    return ifaces


def _parse_mikrotik_routes(output):
    routes = []
    for block in output.split('\n\n'):
        m = _MIKROTIK_ROUTE_RE.search(block)
        if m:
            iface_m = re.search(r'interface=(\S+)', block)
            routes.append({
                'destination': m.group('dest'),
                'next_hop': m.group('nexthop'),
                'interface_name': iface_m.group(1) if iface_m else None,
            })
    return routes


def fetch_host_cache_data(hostid, zabbix_client):
    """Abre UMA sessão SSH no host e traz tudo que o ssh_poller precisa pra
    atualizar o cache (interfaces com IP/descrição/sinal óptico + rotas
    estáticas) -- usado pelo job periódico, nunca pelo agente diretamente.
    Levanta SSHToolError se o host não puder ser consultado."""
    info = _fetch_host_info(hostid, zabbix_client)
    conn = _connect(info)
    try:
        if info['vendor'] == 'huawei':
            brief = conn.send_command('display ip interface brief')
            desc = conn.send_command('display interface description')
            ifaces = _parse_huawei_interfaces(brief, desc)
            for name, data in ifaces.items():
                optical_out = conn.send_command(f'display interface {name} optical-info')
                data['optical_rx_dbm'], data['optical_tx_dbm'] = _parse_optical(optical_out, 'huawei')
            routes_out = conn.send_command('display ip routing-table')
            routes = _parse_huawei_routes(routes_out)
        else:
            addr_out = conn.send_command('/ip address print')
            detail_out = conn.send_command('/interface print detail')
            ifaces = _parse_mikrotik_interfaces(addr_out, detail_out)
            for name, data in ifaces.items():
                try:
                    optical_out = conn.send_command(f'/interface ethernet monitor {name} once')
                    data['optical_rx_dbm'], data['optical_tx_dbm'] = _parse_optical(optical_out, 'mikrotik')
                except Exception:
                    data['optical_rx_dbm'] = data['optical_tx_dbm'] = None
            routes_out = conn.send_command('/ip route print where static detail')
            routes = _parse_mikrotik_routes(routes_out)
        return ifaces, routes
    finally:
        conn.disconnect()
