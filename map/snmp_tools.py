"""Teste de conectividade SNMP sob demanda -- usado pelo botão "Testar SNMP"
na tela de Hosts (e automaticamente logo após salvar um host), pra dar
feedback imediato sem esperar o próximo ciclo de polling do Zabbix. Só faz
um GET em sysDescr.0; não substitui a coleta de métricas, que continua
inteiramente a cargo do Zabbix.

pysnmp==4.4.12 precisa de pyasn1<0.5 (a API interna que ele usa foi removida
em versões mais novas) -- ver requirements.txt."""
from pysnmp.hlapi import (
    CommunityData, ContextData, ObjectIdentity, ObjectType,
    SnmpEngine, UdpTransportTarget, getCmd,
)

from zabbix_client import ZabbixAPIError

SYS_DESCR_OID = '1.3.6.1.2.1.1.1.0'
TIMEOUT_SECONDS = 3


class SNMPToolError(Exception):
    """Erro conhecido (sem interface SNMP, timeout, community recusada) --
    sempre com mensagem segura pra mostrar ao usuário."""


def _fetch_snmp_info(hostid, zabbix_client):
    try:
        hosts = zabbix_client.call('host.get', {
            'hostids': [hostid],
            'output': ['hostid', 'host'],
            'selectInterfaces': ['ip', 'port', 'details'],
        })
    except ZabbixAPIError as e:
        raise SNMPToolError(f'Falha ao consultar o Zabbix: {e}') from e
    if not hosts:
        raise SNMPToolError(f'Host {hostid} não encontrado no Zabbix')

    host = hosts[0]
    ifaces = host.get('interfaces') or []
    if not ifaces:
        raise SNMPToolError(f'Host {host["host"]} não tem interface cadastrada')

    iface = ifaces[0]
    ip = iface.get('ip')
    port = int(iface.get('port') or 161)
    community = (iface.get('details') or {}).get('community') or 'public'
    if not ip:
        raise SNMPToolError(f'Host {host["host"]} não tem IP cadastrado')

    return {'name': host['host'], 'ip': ip, 'port': port, 'community': community}


def test_snmp(hostid, zabbix_client):
    """GET em sysDescr.0 -- só confirma que o agente SNMP responde com essa
    community/porta, sem interpretar o conteúdo retornado."""
    info = _fetch_snmp_info(hostid, zabbix_client)

    iterator = getCmd(
        SnmpEngine(),
        CommunityData(info['community']),
        UdpTransportTarget((info['ip'], info['port']), timeout=TIMEOUT_SECONDS, retries=1),
        ContextData(),
        ObjectType(ObjectIdentity(SYS_DESCR_OID)),
    )
    error_indication, error_status, _error_index, _var_binds = next(iterator)

    if error_indication:
        raise SNMPToolError(
            f'Não respondeu em {info["ip"]}:{info["port"]} ({error_indication})'
        )
    if error_status:
        raise SNMPToolError(
            f'Community/porta recusada por {info["ip"]}:{info["port"]} ({error_status.prettyPrint()})'
        )
    return f'Respondeu em {info["name"]} ({info["ip"]}:{info["port"]})'
