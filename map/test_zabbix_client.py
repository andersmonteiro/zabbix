import pytest

from zabbix_client import ZabbixClient, ZabbixAPIError


def test_login_success(requests_mock):
    requests_mock.post('http://zabbix-frontend:8080/api_jsonrpc.php', json={
        'jsonrpc': '2.0', 'result': 'abc123token', 'id': 1,
    })
    client = ZabbixClient('http://zabbix-frontend:8080', 'Admin', 'secret')
    token = client.login()
    assert token == 'abc123token'


def test_login_raises_on_api_error(requests_mock):
    requests_mock.post('http://zabbix-frontend:8080/api_jsonrpc.php', json={
        'jsonrpc': '2.0',
        'error': {'code': -32602, 'message': 'Invalid params.', 'data': 'Login name or password is incorrect.'},
        'id': 1,
    })
    client = ZabbixClient('http://zabbix-frontend:8080', 'Admin', 'wrong')
    with pytest.raises(ZabbixAPIError):
        client.login()


def test_get_items_logs_in_first_then_fetches(requests_mock):
    requests_mock.post('http://zabbix-frontend:8080/api_jsonrpc.php', [
        {'json': {'jsonrpc': '2.0', 'result': 'abc123token', 'id': 1}},
        {'json': {'jsonrpc': '2.0', 'result': [
            {'itemid': '55010', 'lastvalue': '1', 'lastclock': '1700000000'},
            {'itemid': '55011', 'lastvalue': '-19.4', 'lastclock': '1700000000'},
        ], 'id': 2}},
    ])
    client = ZabbixClient('http://zabbix-frontend:8080', 'Admin', 'secret')
    items = client.get_items(['55010', '55011'])
    assert items['55010']['lastvalue'] == '1'
    assert items['55011']['lastvalue'] == '-19.4'


def test_get_items_empty_list_skips_request(requests_mock):
    client = ZabbixClient('http://zabbix-frontend:8080', 'Admin', 'secret')
    assert client.get_items([]) == {}
    assert requests_mock.call_count == 0


def test_get_items_raises_on_api_error(requests_mock):
    requests_mock.post('http://zabbix-frontend:8080/api_jsonrpc.php', [
        {'json': {'jsonrpc': '2.0', 'result': 'abc123token', 'id': 1}},
        {'json': {'jsonrpc': '2.0', 'error': {'code': -32500, 'message': 'App error.', 'data': 'No permissions'}, 'id': 2}},
    ])
    client = ZabbixClient('http://zabbix-frontend:8080', 'Admin', 'secret')
    with pytest.raises(ZabbixAPIError):
        client.get_items(['55010'])
