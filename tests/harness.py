"""Shared HTTP/auth/home test harness (Plan 124).

Single home for the server-based fixtures previously copied across peer
test modules: auth-file creation, router state, server startup, raw HTTP
helpers, credential stubs, and isolated homes. Semantics are verbatim
copies of the originals; any behavioural difference is a defect.

Kept contracts (do not silently unify):
- ``StubCredentials``: the ``tests/test_mixed_router.py`` class contract
  (``.key`` attribute plus ``key_for``). ``_start_server`` defaults to it.
- ``stub_credentials``: the ``SimpleNamespace`` lambda contract from
  ``tests/test_agent_containment.py`` / ``tests/test_providers.py``.
- ``post``: the ``(port, path, payload, headers=None)`` contract shared
  verbatim by ``tests/test_handler.py``, ``tests/test_v2_compaction.py``
  and ``tests/test_lifecycle.py`` (the latter always passes no headers).
- ``get``: the ``(port, path)`` contract from ``tests/test_lifecycle.py``
  and ``tests/test_claude_ingress.py``.
- ``isolated_home``: the superset contract (returns the temp dir string);
  both prior copies (``test_tool_adapter`` returns it, ``test_v2_compaction``
  returns ``None``) cleared ``_MEMORY``, so the harness keeps that.
- ``tmp_home``: bare temp dir as a ``Path`` with cleanup, no env patch.

Out of scope on purpose: form-encoded setup ``_post``/``_get`` variants
(``tests/test_setup_handler.py``), bound-method ``_post`` helpers with
narrower signatures, and ``tests/fakes.py`` / ``tests/_platform.py``.
"""
import contextlib
import http.client
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ai_router import router as _router_mod, transport as _transport
from ai_router.discovered import _MEMORY
from ai_router.router import Router


class StubCredentials:
    def __init__(self, key='router-secret'):
        self.key = key

    def key_for(self, provider_id=None):
        return self.key

    def key_missing(self, provider_id=None):
        return None


def stub_credentials(key='router-secret'):
    return SimpleNamespace(key_for=lambda _pid=None: key)


def test_state(auth_path):
    return {'port': 0, 'token': 'test-token',
            'openai_models': [], 'opencode_auth': auth_path}


def start_server(state, credentials=None):
    # Isolate tests from the machine's installed router: without an explicit
    # credential object the real openrouter.key would win the ordered lookup
    # and every contract test would see the operator's live key.
    server = Router(state, credentials=(credentials if credentials is not None
                                        else StubCredentials('test-key')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def start_auth_server(test):
    server = start_server(test_state(auth_file(test)))
    test.addCleanup(server.shutdown)
    return server


def auth_file(test):
    auth = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
    json.dump({'openrouter': {'type': 'api', 'key': 'test-key'}}, auth)
    auth.close()
    test.addCleanup(os.unlink, auth.name)
    return auth.name


def post(port, path, payload, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    conn.request('POST', path, body=json.dumps(payload),
                 headers={'Content-Type': 'application/json', **(headers or {})})
    return conn.getresponse()


def get(port, path):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    conn.request('GET', path)
    return conn.getresponse()


@contextlib.contextmanager
def scaled_limits(cap, ceiling=None):
    """Scale the ordinary threshold and the request ceiling (6x unless given)."""
    with mock.patch.object(_router_mod, 'MAX_BODY', cap), \
            mock.patch.object(_transport, 'MAX_REQUEST_BYTES',
                              cap * 6 if ceiling is None else ceiling):
        yield


def isolated_home(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    _MEMORY.clear()
    test.addCleanup(_MEMORY.clear)
    patcher = mock.patch.dict(os.environ, {'ROUTER_HOME': tmp})
    patcher.start()
    test.addCleanup(patcher.stop)
    return tmp


def tmp_home(test):
    home = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, home, True)
    return home


__all__ = ['StubCredentials', 'stub_credentials', 'test_state',
           'start_server', 'start_auth_server', 'auth_file', 'post',
           'get', 'scaled_limits', 'isolated_home', 'tmp_home']
