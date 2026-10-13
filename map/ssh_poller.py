import logging
import time
from datetime import datetime, timezone

from conn_status import get_or_create_conn_status
from models import InterfaceCache, Point, RouteCache
from ssh_tools import SSHToolError, fetch_host_cache_data

logger = logging.getLogger(__name__)


def _refresh_point(session, point, zabbix_client):
    ifaces, routes = fetch_host_cache_data(point.zabbix_hostid, zabbix_client)

    session.query(InterfaceCache).filter(InterfaceCache.point_id == point.id).delete()
    for name, data in ifaces.items():
        session.add(InterfaceCache(
            point_id=point.id, interface_name=name,
            ip_address=data.get('ip_address'), description=data.get('description'),
            optical_rx_dbm=data.get('optical_rx_dbm'), optical_tx_dbm=data.get('optical_tx_dbm'),
        ))

    session.query(RouteCache).filter(RouteCache.point_id == point.id).delete()
    for route in routes:
        session.add(RouteCache(
            point_id=point.id, destination=route['destination'],
            next_hop=route.get('next_hop'), interface_name=route.get('interface_name'),
        ))


def _save_ssh_status(session, hostid, ok):
    """Mesma conexão SSH já aberta por _refresh_point (sucesso ou
    SSHToolError) também alimenta HostConnectivityStatus -- sem isso o
    indicador de SSH do Dashboard só era atualizado sob demanda (clique
    manual, ou abrindo a tela de Hosts), ficando "sem dado" pra sempre
    pra qualquer host que ninguém testasse manualmente. Host sem
    credencial cadastrada passa por aqui como SSHToolError -> ok=False,
    o que é o resultado certo (sem credencial = não dá pra confirmar
    acesso = down, não "desconhecido")."""
    try:
        status = get_or_create_conn_status(session, hostid)
        status.ssh_last_ok = ok
        status.ssh_last_checked_at = datetime.now(timezone.utc)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception('Falha ao salvar status de conectividade SSH do host %s', hostid)


def ssh_cache_poll_loop(session_factory, zabbix_client, interval_seconds=300, stop_event=None):
    """Roda até stop_event ser setado. A cada ciclo, abre UMA sessão SSH por
    host cadastrado com credencial (não uma por tipo de dado) e atualiza o
    cache de interfaces/rotas -- erro num host só é logado e pulado, nunca
    derruba o ciclo inteiro nem atrasa os outros hosts."""
    while True:
        session = session_factory()
        try:
            points = session.query(Point).filter(
                Point.point_type == 'equipment',
                Point.zabbix_hostid.isnot(None),
            ).all()
            for point in points:
                try:
                    _refresh_point(session, point, zabbix_client)
                    session.commit()
                    _save_ssh_status(session, point.zabbix_hostid, True)
                except SSHToolError:
                    # Host sem SSH configurado, fabricante não suportado, ou
                    # fora do ar -- esperado pra boa parte dos hosts, não é
                    # erro de verdade. Fica em debug pra não poluir o log.
                    session.rollback()
                    logger.debug('Sem cache SSH pro ponto %s', point.id, exc_info=True)
                    _save_ssh_status(session, point.zabbix_hostid, False)
                except Exception:
                    session.rollback()
                    logger.exception('Falha inesperada atualizando cache SSH do ponto %s', point.id)
        finally:
            session.close()

        if stop_event is not None:
            if stop_event.wait(interval_seconds):
                break
        else:
            time.sleep(interval_seconds)
