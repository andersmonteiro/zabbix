import logging
import threading
import time

logger = logging.getLogger(__name__)

SEVERITY_LABELS = {
    0: 'Não classificado', 1: 'Informação', 2: 'Atenção',
    3: 'Média', 4: 'Alta', 5: 'Desastre',
}


class AlertCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._problems = []
        self._last_refresh = None

    def get_all(self):
        with self._lock:
            return list(self._problems)

    def last_refresh(self):
        with self._lock:
            return self._last_refresh

    def update(self, problems):
        with self._lock:
            self._problems = problems
            self._last_refresh = time.time()


RESOLVED_WINDOW_HOURS = 24  # quanto tempo um problema já resolvido continua aparecendo


def _serialize_problem(raw, host_by_triggerid):
    severity = int(raw.get('severity', 0))
    host_name, host_id = host_by_triggerid.get(raw.get('objectid'), ('—', None))
    # r_eventid == '0' quando ainda não resolveu -- mesmo campo que o Zabbix
    # usa pra decidir "PROBLEM" vs "RESOLVED" na tela dele.
    resolved = raw.get('r_eventid', '0') not in (None, '0')
    return {
        'eventid': raw.get('eventid'),
        'name': raw.get('name'),
        'host': host_name,
        'hostid': host_id,
        'severity': severity,
        'severity_label': SEVERITY_LABELS.get(severity, 'Desconhecida'),
        'clock': int(raw.get('clock', 0)),
        'acknowledged': raw.get('acknowledged') == '1',
        'resolved': resolved,
        'resolved_clock': int(raw['r_clock']) if resolved and raw.get('r_clock') else None,
    }


def fetch_problems(zabbix_client, resolved_window_hours=RESOLVED_WINDOW_HOURS):
    """Problemas do Zabbix -- abertos E resolvidos recentemente, igual ao que
    a própria tela de Problemas do Zabbix mostra por padrão (checkbox "Show
    recent problems"). `recent=True` é literalmente essa opção via API;
    time_from limita a janela a resolved_window_hours pra não trazer um
    histórico enorme sem fim. problem.get não tem selectHosts próprio -- o
    host mora no trigger, então problemas cujo objeto é um trigger
    (object=='0', a grande maioria) ganham um trigger.get de acompanhamento
    pra resolver o nome do host. hostid viaja junto com o nome pra o mapa
    conseguir casar problema com Point de forma confiável (nome de host pode
    colidir ou ser renomeado; hostid não)."""
    raw = zabbix_client.call('problem.get', {
        'output': 'extend',
        'sortfield': ['eventid'],
        'sortorder': 'DESC',
        'recent': True,
        'time_from': int(time.time()) - resolved_window_hours * 3600,
    })
    if not raw:
        return []

    triggerids = sorted({p['objectid'] for p in raw if p.get('object') == '0' and p.get('objectid')})
    host_by_triggerid = {}
    if triggerids:
        triggers = zabbix_client.call('trigger.get', {
            'triggerids': triggerids,
            'output': ['triggerid'],
            'selectHosts': ['hostid', 'name'],
        })
        for t in triggers:
            hosts = t.get('hosts') or []
            host_by_triggerid[t['triggerid']] = (
                (hosts[0]['name'], hosts[0]['hostid']) if hosts else ('—', None)
            )

    problems = [_serialize_problem(p, host_by_triggerid) for p in raw]
    problems.sort(key=lambda p: (-p['severity'], -p['clock']))
    return problems


def alert_poll_loop(zabbix_client, cache, interval_seconds=30, stop_event=None):
    """Mirrors poller.poll_loop: a Zabbix failure is logged and skipped, never
    crashes the loop and never touches the cache, so stale alerts age out via
    last_refresh() instead of being silently kept as fresh."""
    while True:
        try:
            cache.update(fetch_problems(zabbix_client))
        except Exception:
            logger.exception('Failed to refresh Zabbix alert cache')

        if stop_event is not None:
            if stop_event.wait(interval_seconds):
                break
        else:
            time.sleep(interval_seconds)
