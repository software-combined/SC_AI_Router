"""Recording fake upstream for handler characterisation tests.

Never opens a network connection. Patch target is
http.client.HTTPSConnection as used by codex_router.router.
"""
import http.client
import json
from pathlib import Path
from unittest import mock

def install_payloads(version):
    rules = Path(__file__).resolve().parents[1] / 'tools' / 'global_instructions.py'
    return {'packaging/VERSION': (version + '\n').encode(),
            'packaging/router_launch.py': b'# launcher\n',
            'tools/global_instructions.py': rules.read_bytes()}


class FakeUpstream:
    def __init__(self, status, body_bytes, headers=()):
        self.status = status
        self._buf = body_bytes
        self._headers = list(headers)
        self._pos = 0

    def getheaders(self):
        return list(self._headers)

    def getheader(self, name, default=None):
        return next((v for k, v in self._headers if k.lower() == name.lower()), default)

    def read(self, amt=None):
        if amt is None:
            amt = len(self._buf) - self._pos
        data = self._buf[self._pos:self._pos + amt]
        self._pos += len(data)
        return data

    def read1(self, count):
        return self.read(count)

    def __iter__(self):
        return iter(self._buf.splitlines(keepends=True))


def install_fake(test, responder):
    """Patch HTTPSConnection; record (host, method, path, body, headers)."""
    recorded = []

    class FakeConn:
        def __init__(self, host, *args, **kwargs):
            self._host = host

        def request(self, method, path, body=None, headers=None):
            recorded.append((self._host, method, path, body, headers))

        def getresponse(self):
            return responder()

        def close(self):
            pass

    patcher = mock.patch.object(http.client, 'HTTPSConnection', FakeConn)
    test.addCleanup(patcher.stop)
    patcher.start()
    return recorded


def static_fetch(latest, blob):
    """Fake fetcher serving a feed doc and a bundle."""
    body = json.dumps(latest).encode()

    def fake_fetch(url):
        return body if url.endswith('.json') else blob

    return fake_fetch
