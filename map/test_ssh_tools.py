import pytest

from ssh_tools import (
    SSHToolError,
    _DIGITS_RE,
    _INTERFACE_RE,
    _huawei_iface_slot_key,
    _looks_like_huawei_cli_error,
    _parse_huawei_interfaces,
    _parse_huawei_optical_brief,
    _parse_huawei_routes,
    _parse_optical,
    _strip_huawei_iface_speed_suffix,
    _validate,
    _validate_ip,
)


# ── Validação de entrada (bloqueio de injeção) ──────────────────────────

def test_validate_accepts_normal_interface_name():
    assert _validate('100GE0/5/0.101', _INTERFACE_RE, 'Interface') == '100GE0/5/0.101'


def test_validate_rejects_newline_injection():
    with pytest.raises(SSHToolError):
        _validate('100GE0/5/0\ndisplay current-configuration', _INTERFACE_RE, 'Interface')


def test_validate_rejects_non_digits_for_vlan():
    with pytest.raises(SSHToolError):
        _validate('301; display current-configuration', _DIGITS_RE, 'VLAN')


def test_validate_ip_accepts_real_ip():
    assert _validate_ip('172.21.4.253', 'IP') == '172.21.4.253'


def test_validate_ip_rejects_injection():
    with pytest.raises(SSHToolError):
        _validate_ip('172.21.4.253\ndisplay current-configuration', 'IP')


# ── Detecção de erro de sintaxe do VRP ──────────────────────────────────

def test_looks_like_huawei_cli_error_detects_short_error():
    assert _looks_like_huawei_cli_error("                          ^\nError: Unrecognized command found at '^' position.")


def test_looks_like_huawei_cli_error_ignores_long_valid_output():
    # Saída real e longa não deve ser confundida com erro mesmo contendo
    # a palavra "Error" incidentalmente em algum lugar improvável.
    valid_output = 'linha de config\n' * 50
    assert not _looks_like_huawei_cli_error(valid_output)


# ── Sufixo de velocidade negociada ("(10G)") ────────────────────────────

def test_strip_huawei_iface_speed_suffix():
    assert _strip_huawei_iface_speed_suffix('25GE0/5/24(10G)') == '25GE0/5/24'


def test_strip_huawei_iface_speed_suffix_no_change_when_absent():
    assert _strip_huawei_iface_speed_suffix('25GE0/5/24') == '25GE0/5/24'


# ── Caminho físico (ignora prefixo de tipo e sub-interface) ─────────────

def test_huawei_iface_slot_key_strips_type_prefix():
    # Confirmado ao vivo: 'display optical-module brief' nomeia a porta
    # como "ETHx/y/z", diferente do nome logico ("100GEx/y/z") usado nos
    # outros comandos -- preciso casar pelo caminho fisico.
    assert _huawei_iface_slot_key('ETH0/5/0') == '0/5/0'
    assert _huawei_iface_slot_key('100GE0/5/0') == '0/5/0'
    assert _huawei_iface_slot_key('25GE0/5/24') == '0/5/24'


def test_huawei_iface_slot_key_strips_subinterface_suffix():
    assert _huawei_iface_slot_key('100GE0/5/0.101') == '0/5/0'


# ── display ip interface brief + display interface description ─────────

def test_parse_huawei_interfaces_basic():
    brief = (
        'Interface                   IP Address/Mask      Physical   Protocol\n'
        '25GE0/5/24                  138.94.201.121/30    up         up\n'
        'Vlanif119                   unassigned           up         down\n'
    )
    desc = (
        'Interface                     PHY     Protocol Description\n'
        '25GE0/5/24                    up      up       SERVIDOR-PROXMOX\n'
        'Vlanif119                     up      down     acessojaime\n'
    )
    ifaces = _parse_huawei_interfaces(brief, desc)
    assert ifaces['25GE0/5/24']['ip_address'] == '138.94.201.121/30'
    assert ifaces['25GE0/5/24']['description'] == 'SERVIDOR-PROXMOX'
    assert ifaces['Vlanif119']['ip_address'] is None


def test_parse_huawei_interfaces_tolerates_trailing_vpn_column():
    # Bug real corrigido nesta sessão: um NE40 maior inclui uma coluna VPN
    # depois de "Protocol" -- a versão antiga (ancorada em fim de linha)
    # não casava e o cache inteiro desse host ficava vazio.
    brief = (
        'Interface                   IP Address/Mask      Physical   Protocol VPN\n'
        '100GE0/5/0                  172.21.4.254/30      up         up       --\n'
    )
    desc = (
        'Interface                     PHY     Protocol Description\n'
        '100GE0/5/0                    up      up       DTC-CASTELO\n'
    )
    ifaces = _parse_huawei_interfaces(brief, desc)
    assert '100GE0/5/0' in ifaces
    assert ifaces['100GE0/5/0']['description'] == 'DTC-CASTELO'


def test_parse_huawei_interfaces_strips_speed_suffix_from_both_sources():
    brief = (
        'Interface                   IP Address/Mask      Physical   Protocol\n'
        '25GE0/5/24(10G)              unassigned           up         up\n'
    )
    desc = (
        'Interface                     PHY     Protocol Description\n'
        '25GE0/5/24(10G)                up      up       SERVIDOR-PROXMOX\n'
    )
    ifaces = _parse_huawei_interfaces(brief, desc)
    assert '25GE0/5/24' in ifaces
    assert '25GE0/5/24(10G)' not in ifaces
    assert ifaces['25GE0/5/24']['description'] == 'SERVIDOR-PROXMOX'


# ── Sinal óptico -- "display transceiver diagnosis interface X" (switch) ─

def test_parse_optical_huawei_switch_format():
    # Saida real confirmada ao vivo contra o switch 6730H -- sem ":" depois
    # de "power" e Tx vem ANTES de Rx.
    output = (
        'Port 100GE0/0/1 transceiver diagnostic information:\n'
        'TxPower(dBm)    0.39  (lane0)  -4.30        4.50         normal\n'
        '                0.19  (lane1)\n'
        'RxPower(dBm)    1.28  (lane0)  -11.51       4.50         normal\n'
        '                2.98  (lane1)\n'
    )
    rx, tx = _parse_optical(output, 'huawei')
    assert rx == 1.28
    assert tx == 0.39


def test_parse_optical_huawei_returns_none_when_no_match():
    rx, tx = _parse_optical('Error: Unrecognized command found', 'huawei')
    assert rx is None and tx is None


# ── Sinal óptico -- "display optical-module brief" (routers NE8000/NE40) ─

_OPTICAL_BRIEF_SAMPLE = (
    '-------------------------------------------------------------------------------------------------------------------------------------------\n'
    'Port                   Status Duplex Type               Wavelength            RxPower     TxPower     Mode             VendorPN            \n'
    '-------------------------------------------------------------------------------------------------------------------------------------------\n'
    'ETH0/5/0               up     full   100G-10km-qsfp28   1295.56nm~1309.14nm   5.98dBm     7.46dBm     SingleMode       QSFP28-LR4          \n'
    '                                                        1295.56nm(Lane0)      -0.19dBm    1.22dBm                                          \n'
    '                                                        1300.05nm(Lane1)      -0.37dBm    2.00dBm                                          \n'
    'ETH0/5/6               up     full   1G-100m-copper     unknown               --          --          CopperMode       OPT-ST01            \n'
    'ETH0/5/24              up     full   10G-300m-sfp+      850nm                 -2.94dBm    -2.60dBm    MultiMode        PRE-SFP10G-SR       \n'
    '-------------------------------------------------------------------------------------------------------------------------------------------\n'
)


def test_parse_huawei_optical_brief_reads_main_port_row():
    result = _parse_huawei_optical_brief(_OPTICAL_BRIEF_SAMPLE)
    assert result['ETH0/5/0'] == (5.98, 7.46)


def test_parse_huawei_optical_brief_single_lane_port():
    result = _parse_huawei_optical_brief(_OPTICAL_BRIEF_SAMPLE)
    assert result['ETH0/5/24'] == (-2.94, -2.60)


def test_parse_huawei_optical_brief_copper_port_has_no_power():
    result = _parse_huawei_optical_brief(_OPTICAL_BRIEF_SAMPLE)
    assert result['ETH0/5/6'] == (None, None)


def test_parse_huawei_optical_brief_ignores_lane_continuation_lines():
    # As linhas de continuação (só wavelength + potência por lane, sem
    # nome de porta) não podem virar entradas falsas no resultado.
    result = _parse_huawei_optical_brief(_OPTICAL_BRIEF_SAMPLE)
    assert '1295.56nm(Lane0)' not in result


# ── Tabela de rotas estáticas ────────────────────────────────────────────

def test_parse_huawei_routes():
    output = (
        'Destination/Mask    Proto   Pre  Cost        Flags NextHop         Interface\n'
        '192.168.1.0/24       Static  60   0             D   10.0.0.1        100GE0/5/0\n'
    )
    routes = _parse_huawei_routes(output)
    assert routes == [{
        'destination': '192.168.1.0/24',
        'next_hop': '10.0.0.1',
        'interface_name': '100GE0/5/0',
    }]


def test_parse_huawei_routes_ignores_non_static_rows():
    # Rota default real de Castelo (EBGP, não estática) -- confirmado ao
    # vivo que ela nunca aparece em listar_rotas_estaticas por isso.
    output = (
        'Destination/Mask    Proto   Pre  Cost        Flags NextHop         Interface\n'
        '        0.0.0.0/0   EBGP    255  0             RD  172.21.4.253    100GE0/5/0.702\n'
    )
    assert _parse_huawei_routes(output) == []
