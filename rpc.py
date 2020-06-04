import requests


class jsonRPC:
    METHOD = {'tts': 'TTS', 'status': 'STATUS', 'control': 'CONTROL', 'volume': 'VOLUME'}

    def __init__(self, ip, port, token=None, timeout=10):
        self.timeout = timeout
        self.ip = ip
        self.port = port
        self.base = "http://{}:{}/".format(ip, port)
        self.token = token
        self.rpc = requests.session()
        self.__index__ = 0

    @property
    def index(self):
        self.__index__ += 1
        return self.__index__

    def __getattr__(self, item):
        def method(**kwargs):
            m = self.METHOD[item]
            return self.get(m, **kwargs)

        if item in self.METHOD:
            return method

    def __requests__(self, payload, timeout=None):
        timeout = timeout or self.timeout
        try:
            response = self.rpc.post(self.base, json=payload, timeout=timeout).json()
            result = response["result"]
        except Exception:
            raise TimeoutError("RPC timeout") from None
        if result["code"] == -5:
            raise ValueError("Token error") from None
        return result

    def get(self, method, **kwargs):
        if self.token:
            kwargs.update(token=self.token)
        payload = {
            "method": method,
            "params": kwargs,
            "jsonrpc": "2.0",
            "id": self.index,
        }
        return self.__requests__(payload)
