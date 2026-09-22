import logging
import threading
import time

logger = logging.getLogger(__name__)


class StatusCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {}
        self._last_refresh = None

    def get(self, itemid):
        with self._lock:
            return self._data.get(itemid)

    def get_all(self):
        with self._lock:
            return dict(self._data)

    def last_refresh(self):
        with self._lock:
            return self._last_refresh

    def update(self, items_by_id):
        with self._lock:
            self._data.update(items_by_id)
            self._last_refresh = time.time()


def poll_loop(zabbix_client, get_itemids_fn, cache, interval_seconds=30, stop_event=None):
    """Runs until stop_event is set. Each iteration fetches the current
    itemids (via get_itemids_fn, so newly-created segments are picked up
    without restarting) and updates the cache. A Zabbix failure is logged
    and skipped — it never crashes the loop, and it never touches the
    cache, so stale data ages out via last_refresh() instead of being
    silently kept as fresh."""
    while True:
        try:
            itemids = get_itemids_fn()
            items = zabbix_client.get_items(itemids)
            cache.update(items)
        except Exception:
            logger.exception('Failed to refresh Zabbix item cache')

        if stop_event is not None:
            if stop_event.wait(interval_seconds):
                break
        else:
            time.sleep(interval_seconds)
