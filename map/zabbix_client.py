import requests


class ZabbixAPIError(Exception):
    pass


class ZabbixClient:
    def __init__(self, url, user, password, insecure=False):
        self.api_url = url.rstrip('/') + '/api_jsonrpc.php'
        self.user = user
        self.password = password
        self.verify = not insecure
        self._auth_token = None

    def _call(self, method, params, request_id, use_auth=False):
        headers = {'Content-Type': 'application/json-rpc'}
        if use_auth:
            headers['Authorization'] = f'Bearer {self._auth_token}'
        resp = requests.post(
            self.api_url,
            json={'jsonrpc': '2.0', 'method': method, 'params': params, 'id': request_id},
            headers=headers, verify=self.verify, timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if 'error' in data:
            raise ZabbixAPIError(data['error'].get('data') or data['error'].get('message'))
        return data['result']

    def login(self):
        self._auth_token = self._call(
            'user.login', {'username': self.user, 'password': self.password}, request_id=1,
        )
        return self._auth_token

    def get_items(self, itemids):
        if not itemids:
            return {}
        if not self._auth_token:
            self.login()
        result = self._call(
            'item.get',
            {'itemids': itemids, 'output': ['itemid', 'lastvalue', 'lastclock']},
            request_id=2, use_auth=True,
        )
        return {item['itemid']: item for item in result}
