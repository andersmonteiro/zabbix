from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, JSON, DateTime, Boolean
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class User(Base):
    __tablename__ = 'netmap_users'

    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class Point(Base):
    __tablename__ = 'netmap_points'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    point_type = Column(String, nullable=False)  # 'waypoint' or 'equipment'

    # Only set when point_type == 'equipment'
    zabbix_hostid = Column(String, nullable=True)
    zabbix_status_itemid = Column(String, nullable=True)  # e.g. ICMP ping / agent availability item
    zabbix_cpu_itemid = Column(String, nullable=True)
    # Separate from zabbix_status_itemid (ping) on purpose -- same reasoning
    # as Segment.zabbix_snmp_available_itemid: a host can answer ping while
    # SNMP itself is down, and the tooltip needs to show both independently.
    zabbix_snmp_available_itemid = Column(String, nullable=True)
    zabbix_uptime_itemid = Column(String, nullable=True)  # sysUpTime, in seconds
    zabbix_latency_itemid = Column(String, nullable=True)  # icmppingsec, in seconds
    equipment_model = Column(String, nullable=True)  # used to look up the photo
    equipment_ip = Column(String, nullable=True)

    # Resultado do último teste de conexão SSH (botão "Testar SSH" na tela de
    # Hosts, ou uma chamada real do agente de IA) -- None = nunca testado,
    # diferente de False (testado e falhou). Credenciais em si continuam só
    # nas macros do host no Zabbix ({$SSH_USER}/{$SSH_PASS}/{$SSH_PORT}),
    # nunca duplicadas aqui.
    ssh_last_ok = Column(Boolean, nullable=True)
    ssh_last_checked_at = Column(DateTime, nullable=True)


class InterfaceCache(Base):
    """Config "que não muda o tempo todo" de cada interface, pré-buscada via
    SSH a cada ciclo do ssh_poller (ver ssh_poller.py) em vez de consultada
    ao vivo toda vez que o agente pergunta -- IP, descrição (pra responder
    "qual porta vai pra localidade Y") e sinal óptico. BGP e log ficam de
    fora de propósito: são estado ao vivo, não config, cachear dá resposta
    errada."""
    __tablename__ = 'netmap_interface_cache'

    id = Column(Integer, primary_key=True)
    point_id = Column(Integer, ForeignKey('netmap_points.id'), nullable=False)
    interface_name = Column(String, nullable=False)
    ip_address = Column(String, nullable=True)
    description = Column(String, nullable=True)
    optical_rx_dbm = Column(Float, nullable=True)
    optical_tx_dbm = Column(Float, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class RouteCache(Base):
    """Rotas estáticas de cada host -- mesma lógica do InterfaceCache, config
    que raramente muda."""
    __tablename__ = 'netmap_route_cache'

    id = Column(Integer, primary_key=True)
    point_id = Column(Integer, ForeignKey('netmap_points.id'), nullable=False)
    destination = Column(String, nullable=False)
    next_hop = Column(String, nullable=True)
    interface_name = Column(String, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class Circuit(Base):
    __tablename__ = 'netmap_circuits'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


class Segment(Base):
    __tablename__ = 'netmap_segments'

    id = Column(Integer, primary_key=True)
    circuit_id = Column(Integer, ForeignKey('netmap_circuits.id'), nullable=False)
    order_index = Column(Integer, nullable=False)
    origin_point_id = Column(Integer, ForeignKey('netmap_points.id'), nullable=False)
    destination_point_id = Column(Integer, ForeignKey('netmap_points.id'), nullable=False)
    waypoint_ids = Column(JSON, nullable=False, default=list)  # ordered list of Point.id (point_type='waypoint')

    # "Lado A" (origem) -- nomes sem sufixo por serem os originais, de antes
    # do segmento monitorar as duas pontas.
    zabbix_speed_itemid = Column(String, nullable=True)
    zabbix_throughput_in_itemid = Column(String, nullable=True)
    zabbix_throughput_out_itemid = Column(String, nullable=True)
    zabbix_optical_rx_itemid = Column(String, nullable=True)
    zabbix_optical_tx_itemid = Column(String, nullable=True)
    zabbix_error_itemid = Column(String, nullable=True)
    # "Lado B" (destino) -- itens da interface do outro lado do link. Cada
    # ponta de um circuito físico tem seus próprios contadores (throughput,
    # sinal óptico); mostrar só um lado escondia problemas que só aparecem
    # do outro lado (ex: RX ruim de um lado só). Nulo em segmentos antigos
    # até serem reabertos e salvos de novo pelo formulário Lado A/B.
    zabbix_speed_itemid_b = Column(String, nullable=True)
    zabbix_throughput_in_itemid_b = Column(String, nullable=True)
    zabbix_throughput_out_itemid_b = Column(String, nullable=True)
    zabbix_optical_rx_itemid_b = Column(String, nullable=True)
    zabbix_optical_tx_itemid_b = Column(String, nullable=True)
    zabbix_operstatus_itemid_b = Column(String, nullable=True)
    # Free-text label (e.g. "100GE0/0/1 - KM30-40G"), not an itemid -- the
    # port name is stable and Zabbix has no single item that returns just
    # the friendly name, so it's filled in once when the segment is wired up.
    port_name = Column(String, nullable=True)
    zabbix_operstatus_itemid = Column(String, nullable=True)
    # Separate from operstatus on purpose: a host can be alive (ping up) while
    # SNMP itself is unreachable, in which case the link should still read
    # "up" (driven by ping) but flagged so an operator knows the interface
    # detail (traffic, real port state) isn't trustworthy right now.
    zabbix_snmp_available_itemid = Column(String, nullable=True)
    signal_warn_threshold_dbm = Column(Float, nullable=True)

    circuit = relationship('Circuit', backref='segments')
    origin = relationship('Point', foreign_keys=[origin_point_id])
    destination = relationship('Point', foreign_keys=[destination_point_id])


def get_engine(database_url):
    return create_engine(database_url, pool_pre_ping=True)


def get_session_factory(engine):
    return sessionmaker(bind=engine)


def init_db(engine):
    Base.metadata.create_all(engine)
