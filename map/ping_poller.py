import logging
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from models import Point

logger = logging.getLogger(__name__)

PING_TIMEOUT_SECONDS = 2
PING_WORKERS = 8


class PingCache:
    """True = respondeu, False = não respondeu -- chaveado por point.id
    (não por IP: dois pontos podem ter o mesmo IP temporariamente durante
    uma troca de equipamento, e point.id é o que build_map_state já usa
    pra tudo mais). Ausente = nunca testado (poller não rodou ainda, ou
    o ponto não tinha IP no último ciclo)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {}
        self._last_refresh = None

    def get(self, point_id):
        with self._lock:
            return self._data.get(point_id)

    def last_refresh(self):
        with self._lock:
            return self._last_refresh

    def update(self, results):
        with self._lock:
            self._data = results
            self._last_refresh = time.time()


def _ping_once(ip):
    try:
        result = subprocess.run(
            ['ping', '-c', '1', '-W', str(PING_TIMEOUT_SECONDS), ip],
            capture_output=True, timeout=PING_TIMEOUT_SECONDS + 2,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def ping_poll_loop(session_factory, cache, interval_seconds=30, stop_event=None):
    """Ping ICMP direto em cada ponto 'equipment' com IP cadastrado --
    independente de o host ter (ou não) um item de disponibilidade do
    Zabbix vinculado. Usado em build_map_state como fallback quando esse
    item não existe ou está sem dado, pra um host não ficar 'unknown'
    só porque ninguém configurou o item certo pra ele. Substitui o dict
    inteiro a cada ciclo (não faz merge) -- um ponto removido do mapa
    some do cache em vez de ficar com um resultado velho pra sempre."""
    while True:
        session = session_factory()
        try:
            points = session.query(Point).filter(
                Point.point_type == 'equipment',
                Point.equipment_ip.isnot(None),
            ).all()
            targets = {p.id: p.equipment_ip for p in points if p.equipment_ip}
        finally:
            session.close()

        if targets:
            try:
                with ThreadPoolExecutor(max_workers=PING_WORKERS) as executor:
                    oks = list(executor.map(_ping_once, targets.values()))
                cache.update(dict(zip(targets.keys(), oks)))
            except Exception:
                logger.exception('Falha inesperada no poller de ping ICMP')

        if stop_event is not None:
            if stop_event.wait(interval_seconds):
                break
        else:
            time.sleep(interval_seconds)
