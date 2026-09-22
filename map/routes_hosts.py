from flask import Blueprint, jsonify, request

from zabbix_client import ZabbixAPIError

hosts_bp = Blueprint('zbx_hosts', __name__, url_prefix='/api/zabbix')

_zabbix_client = None

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


def init_hosts_routes(zabbix_client):
    global _zabbix_client
    _zabbix_client = zabbix_client


def _resolve_vendor_template_ids(vendor):
    names = VENDOR_TEMPLATE_SETS.get((vendor or '').strip().lower())
    if not names:
        return []
    templates = _zabbix_client.call('template.get', {
        'output': ['templateid', 'name'], 'filter': {'host': names},
    })
    return [t['templateid'] for t in templates]


def _serialize_host(h):
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
    return jsonify([_serialize_host(h) for h in hosts])


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
    if data.get('ssh_pass'):
        macros.append({'macro': '{$SSH_PASS}', 'value': data['ssh_pass']})
    if data.get('ssh_port'):
        macros.append({'macro': '{$SSH_PORT}', 'value': data['ssh_port']})

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
    return jsonify({'hostid': result['hostids'][0]}), 201


@hosts_bp.route('/hosts/<hostid>', methods=['DELETE'])
def delete_host(hostid):
    try:
        _zabbix_client.call('host.delete', [hostid])
    except ZabbixAPIError as e:
        return jsonify({'error': str(e)}), 502
    return '', 204
