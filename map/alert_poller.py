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


def _serialize_problem(raw, host_by_triggerid):
    severity = int(raw.get('severity', 0))
    host_name, host_id = host_by_triggerid.get(raw.get('objectid'), ('—', None))
    return {
        'eventid': raw.get('eventid'),
        'name': raw.get('name'),
        'host': host_name,
        'hostid': host_id,
        'severity': severity,
        'severity_label': SEVERITY_LABELS.get(severity, 'Desconhecida'),
        'clock': int(raw.get('clock', 0)),
        'acknowledged': raw.get('acknowledged') == '1',
    }


def fetch_problems(zabbix_client):
    """Currently unresolved Zabbix problems (recent=False excludes ones that
    already recovered), newest+most severe first. problem.get has no
    selectHosts of its own -- the host lives on the trigger, so problems
    whose object is a trigger (object=='0', the vast majority) get a
    follow-up trigger.get to resolve host names. hostid travels alongside the
    name so the map can match problems to Points reliably (host names can
    collide or get renamed; hostid doesn't)."""
    raw = zabbix_client.call('problem.get', {
        'output': 'extend',
        'sortfield': ['eventid'],
        'sortorder': 'DESC',
        'recent': False,
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
