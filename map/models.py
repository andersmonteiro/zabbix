from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, JSON, DateTime
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
    equipment_model = Column(String, nullable=True)  # used to look up the photo
    equipment_ip = Column(String, nullable=True)


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

    zabbix_speed_itemid = Column(String, nullable=True)
    zabbix_throughput_in_itemid = Column(String, nullable=True)
    zabbix_throughput_out_itemid = Column(String, nullable=True)
    zabbix_optical_rx_itemid = Column(String, nullable=True)
    zabbix_error_itemid = Column(String, nullable=True)
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
