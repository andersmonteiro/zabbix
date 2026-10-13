from models import HostConnectivityStatus


def get_or_create_conn_status(session, hostid):
    """Shared between routes_hosts.py (manual test button) and
    ssh_poller.py (periodic background test) -- both write to the same
    HostConnectivityStatus row per zabbix_hostid."""
    status = session.query(HostConnectivityStatus).filter(
        HostConnectivityStatus.zabbix_hostid == hostid
    ).first()
    if status is None:
        status = HostConnectivityStatus(zabbix_hostid=hostid)
        session.add(status)
    return status
