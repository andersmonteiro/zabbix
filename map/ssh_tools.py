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
import ipaddress
import logging
import re
import socket

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

from zabbix_client import ZabbixAPIError

logger = logging.getLogger(__name__)

# {$VENDOR} no Zabbix -> device_type do netmiko. Datacom (DmOS) não tem
# driver nativo no netmiko -- 'cisco_ios' é o genérico mais próximo pro
# estilo de CLI real (prompt "host#", comandos "show ..."): detecta esse
# prompt corretamente e tenta desabilitar paginação ("terminal length 0"),
# o que não quebra nada mesmo se o DmOS ignorar o comando.
_NETMIKO_DEVICE_TYPE = {
    'huawei': 'huawei',
    'mikrotik': 'mikrotik_routeros',
    'datacom': 'cisco_ios',
}

CONNECT_TIMEOUT = 8
PORT_CHECK_TIMEOUT = 5


_INTERFACE_RE = re.compile(r'^[A-Za-z0-9/.:_ -]{1,80}$')
_DIGITS_RE = re.compile(r'^[0-9]{1,10}$')
_LOGIN_FRAGMENT_RE = re.compile(r'^[A-Za-z0-9@._-]{1,80}$')
_LOG_SINCE_RE = re.compile(r'^[0-9/:\- ]{1,40}$')


def _validate(value, pattern, label):
    """Todo parâmetro que vira texto de comando (nome de interface, vlan,
    IP, trecho de login, etc) passa por aqui antes do f-string -- o
    próprio CLI do equipamento trata um "\\n" dentro do valor como Enter
    no meio do comando, então sem isso uma pergunta cujo parâmetro vem
    quase direto da pergunta do usuário (ex: trecho de login PPPoE)
    poderia injetar um segundo comando na mesma sessão SSH. Rejeita em
    vez de tentar sanitizar: qualquer coisa fora do formato esperado
    nunca é um valor válido de verdade pra essas categorias."""
    text = str(value or '')
    if not pattern.match(text):
        raise SSHToolError(f'{label} inválido: "{text}"')
    return text


def _validate_ip(value, label):
    text = str(value or '')
    try:
        ipaddress.ip_address(text)
    except ValueError:
        raise SSHToolError(f'{label} não é um IP válido: "{text}"')
    return text


def _looks_like_huawei_cli_error(output):
    """VRP devolve erro de sintaxe como texto de comando normal (nunca
    levanta exceção no netmiko) -- ex: "Error: Wrong parameter found at
    '^' position." ou "Error: Unrecognized command found at '^'
    position.". Essas mensagens são sempre curtas; uma saída de comando
    válida (config, tabela, etc) nunca é tão curta quanto isso, então o
    tamanho + a assinatura "Error:" já diferencia um do outro sem falso
    positivo observado nas saídas reais vistas neste projeto."""
    return len(output) < 200 and 'Error:' in output


class SSHToolError(Exception):
    """Erro conhecido (sem credencial, fabricante não suportado, falha de
    conexão) -- sempre com mensagem segura pra mostrar ao usuário/modelo."""


class SSHAuthError(SSHToolError):
    """Usuário/senha recusados -- diferente de timeout ou sem credencial
    cadastrada. Equipamentos (Huawei em especial) têm proteção anti-
    bruteforce que bloqueia o IP de origem após N tentativas de login
    malsucedidas; ssh_poller.py usa esse tipo especificamente pra aplicar
    um cooldown bem mais longo, em vez de tentar de novo no próximo ciclo
    normal com a mesma credencial errada."""


def _fetch_basic_host_info(hostid, zabbix_client):
    """Dados mínimos de conectividade (IP, porta, vendor, credencial) --
    não valida se o vendor tem driver netmiko nem se a credencial está
    presente. Usado por test_ssh pra permitir um teste de PORTA (sem
    autenticar) mesmo em vendors sem suporte a comandos ainda (Datacom)."""
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
    ssh_port = macros.get('{$SSH_PORT}') or '22'

    if not ip:
        raise SSHToolError(f'Host {host["host"]} não tem IP cadastrado')

    return {
        'name': host['host'],
        'vendor': vendor,
        'ip': ip,
        'port': int(ssh_port),
        'username': macros.get('{$SSH_USER}'),
        'password': macros.get('{$SSH_PASS}'),
    }


def _fetch_host_info(hostid, zabbix_client):
    """Igual a _fetch_basic_host_info, mas exige vendor com driver
    netmiko e credencial presente -- usado por tudo que precisa rodar
    comando de verdade (não só testar se a porta responde)."""
    info = _fetch_basic_host_info(hostid, zabbix_client)
    if info['vendor'] not in _NETMIKO_DEVICE_TYPE:
        raise SSHToolError(
            f'Fabricante "{info["vendor"] or "não definido"}" não suportado via SSH '
            '(só Huawei, Mikrotik e Datacom por enquanto)'
        )
    if not info['username'] or not info['password']:
        raise SSHToolError(f'Host {info["name"]} não tem credencial SSH cadastrada')
    info['device_type'] = _NETMIKO_DEVICE_TYPE[info['vendor']]
    return info


def _check_tcp_port(ip, port, timeout=PORT_CHECK_TIMEOUT):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


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
        raise SSHAuthError(f'Usuário/senha SSH recusados por {info["ip"]}') from e
    except NetmikoTimeoutException as e:
        raise SSHToolError(f'Não respondeu na porta SSH ({info["ip"]}:{info["port"]})') from e
    except Exception as e:
        raise SSHToolError(f'Falha ao conectar em {info["ip"]}: {e}') from e


def test_ssh(hostid, zabbix_client):
    """Pra vendor com driver (Huawei/Mikrotik): abre e autentica de
    verdade, sem rodar comando nenhum. Pra vendor sem driver ainda (ex:
    Datacom, antes de termos os comandos reais pra implementar o
    parser): só confirma que a porta SSH está respondendo -- não é uma
    confirmação de credencial, só de que o host está no ar e a porta
    está aberta, melhor que nada enquanto o suporte completo não existe."""
    info = _fetch_basic_host_info(hostid, zabbix_client)
    if info['vendor'] in _NETMIKO_DEVICE_TYPE:
        if not info['username'] or not info['password']:
            raise SSHToolError(f'Host {info["name"]} não tem credencial SSH cadastrada')
        info['device_type'] = _NETMIKO_DEVICE_TYPE[info['vendor']]
        conn = _connect(info)
        conn.disconnect()
        return f'Conectado em {info["name"]} ({info["ip"]}) como {info["username"]}'

    if _check_tcp_port(info['ip'], info['port']):
        return (
            f'Porta SSH ({info["port"]}) respondendo em {info["name"]} ({info["ip"]}) -- '
            f'fabricante "{info["vendor"] or "não definido"}" ainda sem suporte a comandos'
        )
    raise SSHToolError(f'Não respondeu na porta SSH ({info["ip"]}:{info["port"]})')


def get_optical_signal(hostid, port, zabbix_client):
    port = _validate(port, _INTERFACE_RE, 'Interface')
    info = _fetch_host_info(hostid, zabbix_client)
    conn = _connect(info)
    try:
        if info['vendor'] == 'huawei':
            output = conn.send_command(f'display transceiver diagnosis interface {port}')
            if _looks_like_huawei_cli_error(output):
                # Confirmado ao vivo (2026-10-14): esse comando funciona em
                # switches Huawei (S/CloudEngine, ex: 6730H) mas é
                # "Unrecognized command" num roteador NE8000/NE40 -- VRP não
                # é um dialeto só, e a sintaxe certa pra essa família ainda
                # não está cadastrada na Base de Conhecimento. Recusa
                # explícita em vez de devolver o erro de sintaxe cru do
                # equipamento pro modelo tentar interpretar sozinho.
                raise SSHToolError(
                    f'Sinal óptico não suportado nesse equipamento Huawei pra a interface "{port}" '
                    '(comando catalogado só confirmado em switches S/CloudEngine -- routers '
                    'NE8000/NE40 usam uma sintaxe diferente, ainda não cadastrada na Base de '
                    'Conhecimento)'
                )
        elif info['vendor'] == 'datacom':
            # `port` já vem no formato usado pelo próprio equipamento, ex:
            # "ten-gigabit-ethernet 1/1/1" (ver Base de Conhecimento,
            # categoria "Sinal optico de porta especifica").
            output = conn.send_command(f'show interface transceivers {port}')
        else:
            output = conn.send_command(f'/interface ethernet monitor {port} once')
        return output
    finally:
        conn.disconnect()


def get_bgp_prefixes(hostid, neighbor_ip, zabbix_client):
    neighbor_ip = _validate_ip(neighbor_ip, 'IP do vizinho BGP')
    info = _fetch_host_info(hostid, zabbix_client)
    if info['vendor'] == 'datacom':
        raise SSHToolError(
            'BGP não se aplica aos equipamentos Datacom cadastrados (switches L2/L3) -- '
            'nenhum comando de BGP catalogado pra esse fabricante ainda'
        )
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


def _huawei_only_display(hostid, zabbix_client, command, feature_label, read_timeout=None):
    """Compartilhado pelos comandos de BGP/route-policy/prefix-list que só
    têm comando catalogado pra Huawei até agora -- mesma recusa explícita
    (em vez de adivinhar o comando de outro fabricante) que o resto do
    arquivo já usa pra capacidades não catalogadas."""
    info = _fetch_host_info(hostid, zabbix_client)
    if info['vendor'] != 'huawei':
        raise SSHToolError(
            f'{feature_label} só catalogado pra Huawei por enquanto '
            f'(fabricante "{info["vendor"]}" ainda não tem esse comando)'
        )
    conn = _connect(info)
    try:
        kwargs = {'read_timeout': read_timeout} if read_timeout else {}
        return conn.send_command(command, **kwargs)
    finally:
        conn.disconnect()


def get_bgp_peers(hostid, zabbix_client):
    """Lista todas as sessões BGP configuradas, com estado e tempo de
    atividade -- "display bgp peer". Útil pra achar o IP de um vizinho
    pelo contexto quando não se sabe de antemão qual peer corresponde ao
    equipamento perguntado (ver caso real: interface "SERVIDOR-PROXMOX"
    sem nenhum peer configurado nos IPs prováveis do /30)."""
    return _huawei_only_display(hostid, zabbix_client, 'display bgp peer', 'Listagem de sessões BGP')


def get_bgp_peer_detail(hostid, peer_ip, zabbix_client):
    """Estado de UM vizinho BGP específico -- "display bgp peer | include
    <IP>", mais direto que pedir a lista inteira e filtrar na mão."""
    peer_ip = _validate_ip(peer_ip, 'IP do peer BGP')
    return _huawei_only_display(
        hostid, zabbix_client, f'display bgp peer | include {peer_ip}',
        'Consulta de sessão BGP específica',
    )


def get_bgp_config(hostid, zabbix_client):
    """Configuração completa de BGP (AS, vizinhos com descrição, route-policy
    aplicada a cada um, etc) -- "display current configuration bgp".
    Confirmado ao vivo: "current-configuration" (com hífen, igual o resto
    dos comandos "display current-configuration interface X" deste
    arquivo) dá erro de sintaxe pra essa visão especificamente -- aqui é
    "current" e "configuration" como duas palavras separadas."""
    return _huawei_only_display(hostid, zabbix_client, 'display current configuration bgp', 'Configuração de BGP')


def get_route_policy_config(hostid, zabbix_client):
    """Configuração de todos os filtros de rota (route-policy) usados nos
    IN/OUT de BGP -- "display current-configuration route-policy"."""
    return _huawei_only_display(
        hostid, zabbix_client, 'display current-configuration route-policy', 'Configuração de route-policy',
    )


def get_ip_prefix_list(hostid, zabbix_client):
    """Todos os prefixos IPv4 cadastrados pra uso em filtros de BGP --
    "display ip ip-prefix"."""
    return _huawei_only_display(hostid, zabbix_client, 'display ip ip-prefix', 'Lista de prefixos IPv4')


def get_ipv6_prefix_list(hostid, zabbix_client):
    """Todos os prefixos IPv6 cadastrados pra uso em filtros de BGP --
    "display ip ipv6-prefix"."""
    return _huawei_only_display(hostid, zabbix_client, 'display ip ipv6-prefix', 'Lista de prefixos IPv6')


def get_pppoe_summary(hostid, zabbix_client):
    """Resumo com o TOTAL de assinantes PPPoE conectados (IPv4, IPv6,
    Dual-Stack, por domínio, etc) -- "display access-user". Use esta pra
    responder "quantos clientes PPPoE estão conectados", não a listagem
    completa (get_pppoe_sessions), que não traz um total consolidado tão
    direto."""
    return _huawei_only_display(hostid, zabbix_client, 'display access-user', 'Resumo de assinantes PPPoE')


def get_pppoe_sessions(hostid, zabbix_client):
    """Lista TODAS as sessões PPPoE conectadas, uma por assinante: login,
    vlan, interface do PPPoE Server, IP e MAC -- "display access-user
    user-type pppoe". Pode ser uma lista longa (centenas de linhas) --
    read_timeout mais alto que o padrão, mesmo motivo da tabela de rotas
    BGP em fetch_host_cache_data (saída grande pode estourar o timeout
    padrão do netmiko antes de terminar de paginar)."""
    return _huawei_only_display(
        hostid, zabbix_client, 'display access-user user-type pppoe', 'Listagem de sessões PPPoE',
        read_timeout=60,
    )


def get_pppoe_session_by_vlan(hostid, pevlan, zabbix_client):
    """Sessão(ões) PPPoE de uma VLAN de assinante específica --
    "display access-user pevlan <vlan>"."""
    pevlan = _validate(pevlan, _DIGITS_RE, 'VLAN')
    return _huawei_only_display(
        hostid, zabbix_client, f'display access-user pevlan {pevlan}', 'Consulta de PPPoE por VLAN',
    )


def get_pppoe_session_by_username(hostid, username_fragment, zabbix_client):
    """Sessão PPPoE de um assinante pelo login (ou parte dele) --
    "display access-user username | include <trecho>"."""
    username_fragment = _validate(username_fragment, _LOGIN_FRAGMENT_RE, 'Login')
    return _huawei_only_display(
        hostid, zabbix_client, f'display access-user username | include {username_fragment}',
        'Consulta de PPPoE por login',
    )


def get_pppoe_pool_usage(hostid, zabbix_client):
    """Capacidade das pools de IP usadas pelos domínios PPPoE: total,
    usado e porcentagem de ocupação por domínio -- "display ip-pool
    pool-usage". Use pra saber se uma pool está perto de esgotar."""
    return _huawei_only_display(hostid, zabbix_client, 'display ip-pool pool-usage', 'Uso das pools de PPPoE')


def get_pppoe_aaa_fail_record(hostid, pevlan, zabbix_client):
    """Registro de falha de autenticação AAA de assinantes PPPoE de uma
    VLAN -- "display aaa online-fail-record pevlan <vlan>". Serve pra
    achar clientes bloqueados/rejeitados pelo RADIUS, senha/login errados,
    etc."""
    pevlan = _validate(pevlan, _DIGITS_RE, 'VLAN')
    return _huawei_only_display(
        hostid, zabbix_client, f'display aaa online-fail-record pevlan {pevlan}',
        'Registro de falha de autenticação PPPoE',
    )


def get_vlan_ip(hostid, vlan_id, zabbix_client):
    vlan_id = _validate(vlan_id, _DIGITS_RE, 'VLAN')
    info = _fetch_host_info(hostid, zabbix_client)
    if info['vendor'] == 'datacom':
        # A Base de Conhecimento só tem "show running-config dot1q vlan
        # <id>" (em quais portas a vlan está encaminhada) -- dado diferente
        # de "IP da interface dessa vlan", que é o que esta função promete.
        # Sem um comando real catalogado pra isso, melhor recusar do que
        # arriscar casar o vlan_id errado com a interface L3 errada.
        raise SSHToolError(
            'IP de VLAN ainda não catalogado pra Datacom -- '
            'só existe o comando que mostra em quais portas a vlan está encaminhada'
        )
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
    comum, nunca interpolado dentro de um comando montado livremente.
    Ignorado no Huawei e no Datacom: nenhum dos dois comandos catalogados
    pra log (display logbuffer size 100 / show log tail 100) tem filtro de
    data."""
    info = _fetch_host_info(hostid, zabbix_client)
    conn = _connect(info)
    try:
        if info['vendor'] == 'huawei':
            output = conn.send_command('display logbuffer size 100')
        elif info['vendor'] == 'datacom':
            output = conn.send_command('show log tail 100')
        else:
            since = _validate(since, _LOG_SINCE_RE, 'Data/hora')
            output = conn.send_command(f'/log print where time>={since}')
        return output
    finally:
        conn.disconnect()


def get_interface_config(hostid, interface, zabbix_client):
    """Configuração completa de UMA interface (todos os IPs/sub-IPs
    configurados nela, modo da porta, vlans, etc) -- diferente do cache
    de listar_interfaces_equipamento, que só traz o IP principal (Huawei
    'display ip interface brief' não lista os endereços secundários
    "sub"). Use depois de achar o nome da interface certa (ex: pela
    descrição, via listar_interfaces_equipamento)."""
    interface = _validate(interface, _INTERFACE_RE, 'Interface')
    info = _fetch_host_info(hostid, zabbix_client)
    conn = _connect(info)
    try:
        if info['vendor'] == 'huawei':
            output = conn.send_command(f'display current-configuration interface {interface}')
        elif info['vendor'] == 'datacom':
            output = conn.send_command(f'show running-config interface {interface}')
        else:
            output = conn.send_command(f'/interface print detail where name={interface}')
        return output
    finally:
        conn.disconnect()


def get_interface_arp(hostid, interface, zabbix_client):
    """Tabela ARP filtrada por uma interface -- mostra quais dos IPs
    configurados nessa porta (ver get_interface_config) estão de fato
    em uso por algum equipamento, e o MAC de quem está usando."""
    interface = _validate(interface, _INTERFACE_RE, 'Interface')
    info = _fetch_host_info(hostid, zabbix_client)
    conn = _connect(info)
    try:
        if info['vendor'] == 'huawei':
            output = conn.send_command(f'display arp interface {interface}')
        elif info['vendor'] == 'datacom':
            raise SSHToolError(
                'ARP por interface ainda não catalogado pra Datacom -- '
                'nenhum comando confirmado pra isso ainda'
            )
        else:
            output = conn.send_command(f'/ip arp print where interface={interface}')
        return output
    finally:
        conn.disconnect()


def get_interface_status(hostid, interface, zabbix_client):
    """Status operacional detalhado de UMA interface -- se está UP/DOWN
    física e por protocolo, uptime, modo (trunk/access), velocidade,
    tráfego dos últimos 300s e erros -- "display interface <nome>". Só
    Huawei por enquanto. Diferente de get_interface_config (configuração
    estática) e get_optical_signal (sinal óptico)."""
    interface = _validate(interface, _INTERFACE_RE, 'Interface')
    return _huawei_only_display(
        hostid, zabbix_client, f'display interface {interface}', 'Status detalhado de interface',
    )


def get_mac_address_by_vlan(hostid, vlan_id, zabbix_client):
    """Tabela de endereços MAC aprendidos numa VLAN específica -- MAC,
    tipo (dynamic/static) e de qual interface foi aprendido --
    "display mac-address vlan <vlan>". Só Huawei por enquanto."""
    vlan_id = _validate(vlan_id, _DIGITS_RE, 'VLAN')
    return _huawei_only_display(
        hostid, zabbix_client, f'display mac-address vlan {vlan_id}', 'Tabela MAC por VLAN',
    )


def get_vlan_summary(hostid, zabbix_client):
    """Todas as VLANs criadas no equipamento (estáticas, dinâmicas e
    reservadas) -- "display vlan summary". Só Huawei por enquanto."""
    return _huawei_only_display(hostid, zabbix_client, 'display vlan summary', 'Lista de VLANs')


def get_full_config(hostid, zabbix_client):
    """Configuração completa do equipamento: VLANs, interfaces e suas
    descrições, endereços IP, roteamento, filtros, BGP, etc --
    "display current-configuration". Saída pode ser bem longa. Só Huawei
    por enquanto. Pra pegar só a configuração de BGP ou de uma interface
    específica, prefira get_bgp_config / get_interface_config -- mais
    direto e mais barato."""
    return _huawei_only_display(
        hostid, zabbix_client, 'display current-configuration', 'Configuração completa do host',
        read_timeout=60,
    )


# ── Cache periódico (interfaces + rotas estáticas) ──────────────────────

_HUAWEI_BRIEF_RE = re.compile(
    # Sem o '$' preso logo após o Protocol: confirmado em produção que um
    # NE40 maior inclui uma coluna VPN depois disso ("up up --"), que a
    # versão antiga (ancorada em fim de linha ali) não casava -- 0
    # interfaces no cache inteiro desse host por causa disso. Aceita
    # qualquer coisa depois (ou nada), contanto que tenha um separador.
    r'^(?P<name>\S+)\s+(?P<ip>\S+)\s+(?:up|down|\*down|\^down)\s+(?:up|down)(?:\s|$)',
    re.MULTILINE,
)
_HUAWEI_DESC_RE = re.compile(
    r'^(?P<name>\S+)\s+(?:up|down|\*down|\^down|--)\s+(?:up|down|--)\s+(?P<desc>\S.*)$',
    re.MULTILINE,
)
# Saída real de "display transceiver diagnosis interface X" (confirmado
# ao vivo em 2026-10-14): "TxPower(dBm)    0.14  (lane0)" / "RxPower(dBm)
# 1.26  (lane0)" -- sem ":" depois de "power" (o padrão antigo, escrito
# pra um comando diferente que nunca funcionou de verdade, exigia um ":"
# que não existe aqui) e Tx vem ANTES de Rx na saída. Módulo multi-lane
# (100G QSFP28) repete o valor por lane -- pega só a primeira ocorrência
# de cada (lane0), que já é o valor "atual" do transceiver.
_HUAWEI_TX_POWER_RE = re.compile(r'TxPower\(dBm\)\s+(?P<tx>-?\d+\.?\d*)', re.IGNORECASE)
_HUAWEI_RX_POWER_RE = re.compile(r'RxPower\(dBm\)\s+(?P<rx>-?\d+\.?\d*)', re.IGNORECASE)
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


def _strip_huawei_iface_speed_suffix(name):
    """Uma porta que negocia abaixo da capacidade nominal aparece como
    "25GE0/5/24(10G)" em 'display interface description' (confirmado em
    produção) -- mas comandos que recebem o nome da interface como
    argumento (display current-configuration interface, display arp
    interface, ...) rejeitam esse sufixo ("Wrong parameter found").
    Removido aqui pra todo nome cacheado já sair no formato que os outros
    comandos aceitam direto."""
    return re.sub(r'\([^()]*\)$', '', name)


def _parse_huawei_interfaces(brief_output, desc_output):
    ifaces = {}
    for m in _HUAWEI_BRIEF_RE.finditer(brief_output):
        name = _strip_huawei_iface_speed_suffix(m.group('name'))
        ip = m.group('ip')
        ifaces[name] = {'ip_address': None if ip.lower() == 'unassigned' else ip, 'description': None}
    for m in _HUAWEI_DESC_RE.finditer(desc_output):
        name = _strip_huawei_iface_speed_suffix(m.group('name'))
        if name in ifaces:
            ifaces[name]['description'] = m.group('desc').strip() or None
    return ifaces


def _parse_optical(output, vendor):
    if vendor == 'huawei':
        tx_m = _HUAWEI_TX_POWER_RE.search(output)
        rx_m = _HUAWEI_RX_POWER_RE.search(output)
        try:
            tx = float(tx_m.group('tx')) if tx_m else None
            rx = float(rx_m.group('rx')) if rx_m else None
        except (TypeError, ValueError):
            tx = rx = None
        return rx, tx
    m = _MIKROTIK_OPTICAL_RE.search(output)
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


_DATACOM_IFACE_ROW_RE = re.compile(r'^(?P<id>\d+/\d+/\d+)(?:\s+\S+){7}(?:\s{2,}(?P<desc>\S.*?))?\s*$')
_DATACOM_OPTICAL_ROW_RE = re.compile(
    r'^\s*(?P<name>[a-z][a-z\-]*\s+\d+/\d+/\d+(?::\d+)?)\s*\|'
    r'[^|]*\|[^|]*\|[^|]*\|'
    r'\s*(?P<tx>-?\d+\.?\d*)\s*dBm\s*\|'
    r'\s*(?P<rx>-?\d+\.?\d*)\s*dBm',
    re.IGNORECASE | re.MULTILINE,
)


def _parse_datacom_link_descriptions(output):
    """{nome: descrição} a partir de 'show int link'. Cada seção (Ten
    Gigabit Ethernet Interfaces:, Forty Gigabit Ethernet Interfaces:, ...)
    repete os mesmos IDs (1/1/1, 1/1/2...) -- o nome final leva o tipo da
    seção junto (ex: "ten-gigabit-ethernet 1/1/1"), na mesma convenção
    usada por 'show interface transceivers' (ver _parse_datacom_optical),
    o que permite casar as duas saídas pelo nome direto."""
    descriptions = {}
    prefix = None
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.endswith('Interfaces:'):
            prefix = stripped[: -len('Interfaces:')].strip().lower().replace(' ', '-')
            continue
        if prefix is None:
            continue
        m = _DATACOM_IFACE_ROW_RE.match(line)
        if m:
            descriptions[f"{prefix} {m.group('id')}"] = m.group('desc')
    return descriptions


def _parse_datacom_optical(output):
    """{nome: (rx_dbm, tx_dbm)} a partir da tabela de digital-diagnostics
    de 'show interface transceivers' (sem argumento -- é o comando que
    realmente lista todas as portas de uma vez, confirmado contra uma
    saída real; ver observação na Base de Conhecimento). Só entram linhas
    com valor numérico de verdade: a linha-resumo de um transceiver 40G
    multi-lane (sem ":N" no nome) e portas sem módulo óptico aparecem como
    "N/A" nas colunas de potência e são ignoradas."""
    result = {}
    for m in _DATACOM_OPTICAL_ROW_RE.finditer(output):
        try:
            result[m.group('name').strip()] = (float(m.group('rx')), float(m.group('tx')))
        except (TypeError, ValueError):
            continue
    return result


def _parse_datacom_interfaces(link_output, optical_output):
    descriptions = _parse_datacom_link_descriptions(link_output)
    optical = _parse_datacom_optical(optical_output)
    ifaces = {}
    for name in set(descriptions) | set(optical):
        rx, tx = optical.get(name, (None, None))
        ifaces[name] = {
            # Porta física de switch não tem IP próprio (isso é conceito de
            # interface L3/VLAN, não de porta) -- sempre None aqui.
            'ip_address': None,
            'description': descriptions.get(name),
            'optical_rx_dbm': rx,
            'optical_tx_dbm': tx,
        }
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
                # 'display interface X optical-info' nunca foi o comando
                # certo (confirmado quebrado tanto em switch quanto em
                # router) -- o sinal óptico do cache ficou sempre vazio pra
                # Huawei até essa correção. O comando certo só está
                # confirmado em switches S/CloudEngine; em routers
                # NE8000/NE40 ele dá erro de sintaxe (ver get_optical_signal),
                # então o resultado é checado antes de tentar parsear --
                # nesse caso o sinal simplesmente fica None, igual já era
                # antes, só que agora por um motivo conhecido e não por bug.
                optical_out = conn.send_command(f'display transceiver diagnosis interface {name}')
                if not _looks_like_huawei_cli_error(optical_out):
                    data['optical_rx_dbm'], data['optical_tx_dbm'] = _parse_optical(optical_out, 'huawei')
            try:
                # Tabela de rotas de um roteador BGP grande pode ser enorme
                # -- confirmado em produção um NE40 estourar o read_timeout
                # padrão do netmiko nesse comando. Isolado no próprio
                # try/except: se isso falhar mesmo com mais tempo, as
                # interfaces (já coletadas com sucesso acima) não podem
                # ser descartadas também -- sem isso, um timeout aqui
                # jogava fora TUDO, inclusive o que já tinha funcionado.
                routes_out = conn.send_command('display ip routing-table', read_timeout=60)
                routes = _parse_huawei_routes(routes_out)
            except Exception:
                logger.warning(
                    'Falha ao coletar rotas de %s, mantendo as interfaces já coletadas',
                    info['name'], exc_info=True,
                )
                routes = []
        elif info['vendor'] == 'datacom':
            # Ao contrário de Huawei/Mikrotik, 'show interface transceivers'
            # (sem argumento) já devolve o sinal óptico de TODAS as portas
            # de uma vez -- nenhum loop por interface é necessário aqui.
            link_out = conn.send_command('show int link')
            optical_out = conn.send_command('show interface transceivers')
            ifaces = _parse_datacom_interfaces(link_out, optical_out)
            # Nenhum comando de tabela de rotas catalogado pra Datacom
            # ainda (só config de interface L3, que não é a mesma coisa) --
            # fica vazio em vez de adivinhar um comando não confirmado.
            routes = []
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
