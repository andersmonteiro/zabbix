import re
import time
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from models import Point
from snmp_tools import SNMPToolError, test_snmp
from ssh_tools import SSHToolError, test_ssh
from zabbix_client import ZabbixAPIError

hosts_bp = Blueprint('zbx_hosts', __name__, url_prefix='/api/zabbix')

_zabbix_client = None
_session_factory = None
_cache = None
_stale_threshold_seconds = 120

# Confirmado contra dado real de produção (item.get num host Huawei com
# segmento já funcionando) -- são os templates padrão IF-MIB aplicados por
# TODOS os vendors (MW - INTERFACES - FISICAS E VIRTUAIS), não algo
# específico de fabricante:
#   ifOperStatus[100GE0/0/1], ifHCInOctets[100GE0/0/1],
#   ifHCOutOctets[100GE0/0/1], net.if.speed[100GE0/0/1]
_IFACE_KEY_PATTERNS = {
    'operstatus_itemid': re.compile(r'^ifOperStatus\[([^\]]+)\]$'),
    'throughput_in_itemid': re.compile(r'^ifHCInOctets\[([^\]]+)\]$'),
    'throughput_out_itemid': re.compile(r'^ifHCOutOctets\[([^\]]+)\]$'),
    'speed_itemid': re.compile(r'^net\.if\.speed\[([^\]]+)\]$'),
}
# Sinal óptico varia por vendor: Huawei multi-lane separa o nome da interface
# com vírgula (rxpowerML[100GE0/0/1,Ramo 1]); outros templates (ex: Datacom)
# colam o lane junto do nome sem separador -- por isso a chave só captura até
# a primeira vírgula (ou o fim, se não tiver vírgula) e o restante é resolvido
# por prefixo contra os nomes de interface já conhecidos em _extract_interfaces.
_POWER_KEY_PATTERNS = {
    'optical_rx_itemid': re.compile(r'^rxpower(?:ML)?\[([^\],]+)'),
    'optical_tx_itemid': re.compile(r'^txpower(?:ML)?\[([^\],]+)'),
}

# Vendor -> template set, mirroring the mapping used when the SWITCHS group
# was populated by hand. Only SNMP-based templates are auto-applied (no SSH
# macros to fill in before they start collecting data); BGP/health templates
# that require SSH stay a manual follow-up.
VENDOR_TEMPLATE_SETS = {
    'huawei': [
        'MW - HUAWEI - HEALTH - S57xx - S67xx - S127xx - SNMP',
        'MW - HUAWEI - SFP - SNMP - V2',
        'MW - INT. FIS. - ERROS E VELOCIDADE',
        'MW - INTERFACES - FISICAS E VIRTUAIS',
        'MW - SISTEMA - GERAL',
    ],
    'datacom': [
        'MW - DATACOM - HEALTH - DM4xxx',
        'MW - DATACOM - INTERFACES - FISICAS E VIRTUAIS',
        'MW - DATACOM - SFP',
        'MW - INT. FIS. - ERROS E VELOCIDADE',
        'MW - SISTEMA - GERAL',
    ],
    'mikrotik': [
        'MW - MIKROTIK - HEALTH',
        'MW - MIKROTIK - SFP',
        'MW - INT. FIS. - ERROS E VELOCIDADE',
        'MW - SISTEMA - GERAL',
    ],
}


def init_hosts_routes(zabbix_client, session_factory, cache=None, stale_threshold_seconds=120):
    global _zabbix_client, _session_factory, _cache, _stale_threshold_seconds
    _zabbix_client = zabbix_client
    _session_factory = session_factory
    _cache = cache
    _stale_threshold_seconds = stale_threshold_seconds


def _snmp_offline(point):
    """Mesma lógica de routes_map.py (build_map_state) -- None quando o
    poller nunca rodou ou o host não tem o item de disponibilidade SNMP
    configurado, True só quando o último valor coletado é explicitamente 0."""
    if point is None or point.zabbix_snmp_available_itemid is None or _cache is None:
        return None
    last_refresh = _cache.last_refresh()
    if last_refresh is None or (time.time() - last_refresh) > _stale_threshold_seconds:
        return None
    item = _cache.get(point.zabbix_snmp_available_itemid)
    if item is None or item.get('lastclock', '0') == '0':
        return None
    try:
        return int(item['lastvalue']) == 0
    except (TypeError, ValueError):
        return None


def _resolve_vendor_template_ids(vendor):
    names = VENDOR_TEMPLATE_SETS.get((vendor or '').strip().lower())
    if not names:
        return []
    templates = _zabbix_client.call('template.get', {
        'output': ['templateid', 'name'], 'filter': {'host': names},
    })
    return [t['templateid'] for t in templates]


def _build_macros(data, existing_macros=None):
    """Shared by create and update -- host.update replaces the WHOLE macro
    array, so an update must always send the full set (SNMP + optional
    vendor/model/SSH), never just the fields that changed, or the others
    would be silently wiped.

    existing_macros (update only): the host's current {macro: value} in
    Zabbix. The edit form never re-sends the SSH password (host.get doesn't
    return it either, same as any secret), so a blank ssh_pass here means
    "unchanged", not "clear it" -- falling back to the stored value is what
    stops every edit-save from silently wiping a working SSH credential."""
    existing_macros = existing_macros or {}
    community = data.get('community') or 'public'
    port = data.get('port') or '161'
    macros = [
        {'macro': '{$SNMP_COMMUNITY}', 'value': community},
        {'macro': '{$SNMP_PORT}', 'value': port},
    ]
    if data.get('vendor'):
        macros.append({'macro': '{$VENDOR}', 'value': data['vendor']})
    if data.get('model'):
        macros.append({'macro': '{$MODEL}', 'value': data['model']})
    if data.get('ssh_user'):
        macros.append({'macro': '{$SSH_USER}', 'value': data['ssh_user']})
    ssh_pass = data.get('ssh_pass') or existing_macros.get('{$SSH_PASS}')
    if ssh_pass:
        macros.append({'macro': '{$SSH_PASS}', 'value': ssh_pass})
    if data.get('ssh_port'):
        macros.append({'macro': '{$SSH_PORT}', 'value': data['ssh_port']})
    return macros, community, port


def _upsert_point(hostid, data):
    """Creates or updates the map Point tied to this Zabbix host by
    zabbix_hostid, so a host can get its map coordinates from this same
    screen instead of a separate trip through Circuitos. A no-op when lat/lng
    aren't both present -- clearing coordinates here never deletes a Point,
    only setting real values touches it."""
    lat, lng = data.get('lat'), data.get('lng')
    if lat in (None, '') or lng in (None, ''):
        return
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return

    session = _session_factory()
    try:
        point = session.query(Point).filter(Point.zabbix_hostid == hostid).first()
        if point is None:
            session.add(Point(
                name=data.get('name') or hostid, point_type='equipment',
                zabbix_hostid=hostid, lat=lat, lng=lng,
            ))
        else:
            point.lat = lat
            point.lng = lng
            if data.get('name'):
                point.name = data['name']
        session.commit()
    finally:
        session.close()


def _serialize_host(h, point=None):
    iface = h['interfaces'][0] if h.get('interfaces') else {}
    macros = {m['macro']: m['value'] for m in h.get('macros', [])}
    return {
        'hostid': h['hostid'],
        'host': h['host'],
        'ip': iface.get('ip', ''),
        'port': iface.get('port', ''),
        'community': (iface.get('details') or {}).get('community', ''),
        'groups': [g['name'] for g in h.get('hostgroups', [])],
        'vendor': macros.get('{$VENDOR}', ''),
        'model': macros.get('{$MODEL}', ''),
        'ssh_user': macros.get('{$SSH_USER}', ''),
        'ssh_port': macros.get('{$SSH_PORT}', ''),
        'status': 'enabled' if h.get('status') == '0' else 'disabled',
        'lat': point.lat if point is not None else None,
        'lng': point.lng if point is not None else None,
        'ssh_last_ok': point.ssh_last_ok if point is not None else None,
        'ssh_last_checked_at': (
            point.ssh_last_checked_at.isoformat()
            if point is not None and point.ssh_last_checked_at
            else None
        ),
        'snmp_offline': _snmp_offline(point),
    }


@hosts_bp.route('/hosts', methods=['GET'])
def list_hosts():
    try:
        hosts = _zabbix_client.call('host.get', {
            'output': ['hostid', 'host', 'status'],
            'selectInterfaces': ['ip', 'port', 'details'],
            'selectHostGroups': ['name'],
            'selectMacros': ['macro', 'value'],
            'sortfield': 'host',
        })
    except ZabbixAPIError as e:
        return jsonify({'error': str(e)}), 502

    session = _session_factory()
    try:
        points_by_hostid = {
            p.zabbix_hostid: p
            for p in session.query(Point).filter(Point.zabbix_hostid.isnot(None))
        }
    finally:
        session.close()

    return jsonify([_serialize_host(h, points_by_hostid.get(h['hostid'])) for h in hosts])


def _extract_description(item_name, ifname):
    """Zabbix item names carry a human label after the interface name (ex:
    'Status da Interface 100GE0/0/1 - KM30-40G' -> 'KM30-40G', usually what
    the port connects to) -- pulled from ifOperStatus specifically since
    every returned interface is guaranteed to have one and its name never
    carries the extra '- Ramo N' suffix that optical items do."""
    idx = item_name.find(ifname)
    if idx == -1:
        return None
    tail = item_name[idx + len(ifname):].strip().lstrip('-').strip()
    return tail or None


def _extract_interfaces(items):
    """Groups a host's raw Zabbix items into one entry per physical
    interface, keyed by the interface name embedded in the item key --
    this is what lets Circuitos offer a "choose the interface" dropdown
    instead of asking the operator to paste 5 itemids by hand."""
    ifaces = {}
    power_items = []
    for item in items:
        key, itemid, name = item['key_'], item['itemid'], item.get('name', '')
        matched = False
        for field, pattern in _IFACE_KEY_PATTERNS.items():
            m = pattern.match(key)
            if m:
                ifname = m.group(1)
                entry = ifaces.setdefault(ifname, {})
                entry[field] = itemid
                if field == 'operstatus_itemid':
                    entry['description'] = _extract_description(name, ifname)
                matched = True
                break
        if matched:
            continue
        for field, pattern in _POWER_KEY_PATTERNS.items():
            m = pattern.match(key)
            if m:
                power_items.append((field, m.group(1), itemid))
                break

    # Sinal óptico entra por último, casado por prefixo contra os nomes de
    # interface já achados acima -- necessário pro formato "colado" (sem
    # vírgula) de alguns templates (ver comentário de _POWER_KEY_PATTERNS).
    known_names = sorted(ifaces.keys(), key=len, reverse=True)
    for field, content, itemid in power_items:
        name = next((n for n in known_names if content.startswith(n)), content)
        # setdefault: a primeira leitura vence -- um segundo RX/TX pro mesmo
        # nome é outro lane do mesmo SFP multi-lane, não outra interface.
        ifaces.setdefault(name, {}).setdefault(field, itemid)

    return sorted(
        ({'name': name, **fields} for name, fields in ifaces.items() if 'operstatus_itemid' in fields),
        key=lambda i: i['name'],
    )


@hosts_bp.route('/hosts/<hostid>/interfaces', methods=['GET'])
def list_host_interfaces(hostid):
    try:
        items = _zabbix_client.call('item.get', {
            'hostids': [hostid], 'output': ['itemid', 'key_', 'name'],
        })
    except ZabbixAPIError as e:
        return jsonify({'error': str(e)}), 502
    return jsonify(_extract_interfaces(items))


@hosts_bp.route('/host-groups', methods=['GET'])
def list_host_groups():
    try:
        groups = _zabbix_client.call('hostgroup.get', {'output': ['groupid', 'name'], 'sortfield': 'name'})
    except ZabbixAPIError as e:
        return jsonify({'error': str(e)}), 502
    return jsonify(groups)


@hosts_bp.route('/templates', methods=['GET'])
def list_templates():
    try:
        templates = _zabbix_client.call('template.get', {'output': ['templateid', 'name']})
    except ZabbixAPIError as e:
        return jsonify({'error': str(e)}), 502
    return jsonify(sorted(templates, key=lambda t: t['name']))


@hosts_bp.route('/hosts', methods=['POST'])
def create_host():
    data = request.get_json(force=True, silent=True) or {}
    missing = [f for f in ('name', 'ip', 'group_id') if not data.get(f)]
    if missing:
        return jsonify({'error': f"Campos obrigatórios ausentes: {', '.join(missing)}"}), 400

    macros, community, port = _build_macros(data)
    params = {
        'host': data['name'],
        'name': data['name'],
        'groups': [{'groupid': data['group_id']}],
        'interfaces': [{
            'type': 2, 'main': 1, 'useip': 1,
            'ip': data['ip'], 'dns': '', 'port': port,
            'details': {'version': '2', 'bulk': '1', 'community': community},
        }],
        'macros': macros,
        'inventory_mode': -1,
    }
    try:
        template_ids = data.get('template_ids') or _resolve_vendor_template_ids(data.get('vendor'))
    except ZabbixAPIError as e:
        return jsonify({'error': str(e)}), 502
    if template_ids:
        params['templates'] = [{'templateid': t} for t in template_ids]

    try:
        result = _zabbix_client.call('host.create', params)
    except ZabbixAPIError as e:
        return jsonify({'error': str(e)}), 502

    hostid = result['hostids'][0]
    _upsert_point(hostid, data)
    return jsonify({'hostid': hostid}), 201


@hosts_bp.route('/hosts/<hostid>', methods=['PUT'])
def update_host(hostid):
    data = request.get_json(force=True, silent=True) or {}

    try:
        current = _zabbix_client.call('host.get', {
            'hostids': [hostid], 'output': ['hostid'],
            'selectInterfaces': ['interfaceid'], 'selectMacros': ['macro', 'value'],
        })
    except ZabbixAPIError as e:
        return jsonify({'error': str(e)}), 502
    if not current:
        return jsonify({'error': 'Host não encontrado'}), 404

    existing_macros = {m['macro']: m['value'] for m in current[0].get('macros', [])}
    macros, community, port = _build_macros(data, existing_macros)
    params = {'hostid': hostid, 'macros': macros}
    if data.get('name'):
        params['host'] = data['name']
        params['name'] = data['name']
    if data.get('group_id'):
        params['groups'] = [{'groupid': data['group_id']}]

    interfaces = current[0].get('interfaces') or []
    if interfaces and data.get('ip'):
        params['interfaces'] = [{
            'interfaceid': interfaces[0]['interfaceid'],
            'type': 2, 'main': 1, 'useip': 1,
            'ip': data['ip'], 'dns': '', 'port': port,
            'details': {'version': '2', 'bulk': '1', 'community': community},
        }]

    try:
        _zabbix_client.call('host.update', params)
    except ZabbixAPIError as e:
        return jsonify({'error': str(e)}), 502

    _upsert_point(hostid, data)
    return jsonify({'ok': True})


@hosts_bp.route('/hosts/<hostid>/test-ssh', methods=['POST'])
def test_host_ssh(hostid):
    session = _session_factory()
    try:
        point = session.query(Point).filter(Point.zabbix_hostid == hostid).first()
        try:
            message = test_ssh(hostid, _zabbix_client)
            ok = True
        except SSHToolError as e:
            message = str(e)
            ok = False
        if point is not None:
            point.ssh_last_ok = ok
            point.ssh_last_checked_at = datetime.now(timezone.utc)
            session.commit()
        return jsonify({'ok': ok, 'message': message})
    finally:
        session.close()


@hosts_bp.route('/hosts/<hostid>/test-snmp', methods=['POST'])
def test_host_snmp(hostid):
    """Checagem sob demanda (GET em sysDescr.0), pro botão "Testar SNMP" e
    pro teste automático logo após salvar um host. Não persiste resultado --
    o badge de SNMP na lista de Hosts continua vindo do polling contínuo do
    Zabbix (routes_hosts._snmp_offline), que é a fonte de verdade; isto aqui
    é só uma confirmação imediata no momento de preencher a credencial."""
    try:
        message = test_snmp(hostid, _zabbix_client)
        ok = True
    except SNMPToolError as e:
        message = str(e)
        ok = False
    return jsonify({'ok': ok, 'message': message})


@hosts_bp.route('/hosts/<hostid>', methods=['DELETE'])
def delete_host(hostid):
    try:
        _zabbix_client.call('host.delete', [hostid])
    except ZabbixAPIError as e:
        return jsonify({'error': str(e)}), 502
    return '', 204
