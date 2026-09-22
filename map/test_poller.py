import threading

from poller import StatusCache, poll_loop


class FakeZabbixClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get_items(self, itemids):
        self.calls.append(itemids)
        if not self.responses:
            raise RuntimeError('Zabbix unreachable')
        return self.responses.pop(0)


def test_cache_starts_with_no_last_refresh():
    cache = StatusCache()
    assert cache.last_refresh() is None
    assert cache.get('55010') is None


def test_cache_update_stores_items_and_refresh_time():
    cache = StatusCache()
    cache.update({'55010': {'lastvalue': '1'}})
    assert cache.get('55010') == {'lastvalue': '1'}
    assert cache.last_refresh() is not None


def test_poll_loop_runs_once_and_updates_cache():
    cache = StatusCache()
    client = FakeZabbixClient([{'55010': {'lastvalue': '1'}}])
    stop_event = threading.Event()
    stop_event.set()  # makes the loop's wait() return immediately after one iteration

    poll_loop(client, lambda: ['55010'], cache, interval_seconds=0, stop_event=stop_event)

    assert cache.get('55010') == {'lastvalue': '1'}
    assert client.calls == [['55010']]


def test_poll_loop_survives_zabbix_error_without_crashing():
    cache = StatusCache()
    client = FakeZabbixClient([])  # first call raises
    stop_event = threading.Event()
    stop_event.set()

    poll_loop(client, lambda: ['55010'], cache, interval_seconds=0, stop_event=stop_event)

    assert cache.get('55010') is None
    assert cache.last_refresh() is None
