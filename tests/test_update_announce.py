"""The new-model restart offer the updater fires after a landed update.

Unit level: the loopback reply, the platform commands, and the swallow
contract, with the runner, opener and lookup injected. The integration point
(the announce runs after the update log is written) stays in
tests/test_update_channel.py, beside the update-log fixtures.
"""
import contextlib
import http.server
import io
import json
import os
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.install_fixtures import install_mod

NONCE = 'n' * 43
PAGE = 'http://127.0.0.1:9/tok/model-prompt/' + NONCE


class AnnounceTests(unittest.TestCase):
    """The restart offer is best-effort: it must never disturb an update."""

    def setUp(self):
        self.updater = install_mod._updater

    def _reply(self, payload):
        body = json.dumps(payload).encode()

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, size=None):
                return body

        def fake(url, timeout=None):
            fake.url = url
            return Resp()
        return fake

    def _run(self, calls):
        def fake(cmd, **kwargs):
            calls.append(cmd)
            return SimpleNamespace(returncode=0)
        return fake

    def test_macos_notifies_then_opens_the_single_use_page(self):
        calls = []
        fetch = self._reply({'pending': [{'slug': 'a', 'name': 'A'},
                                         {'slug': 'b', 'name': 'B'},
                                         {'slug': 'c', 'name': 'C'},
                                         {'slug': 'd', 'name': 'D'}],
                             'url': PAGE})
        self.updater._announce_new_models({'port': 9, 'token': 'tok'},
                                          _run=self._run(calls), _urlopen=fetch,
                                          platform='darwin')
        self.assertEqual([cmd[0] for cmd in calls], ['osascript', 'open'])
        self.assertIn('A, B, C, +1 more', calls[0][-1])
        self.assertNotIn('tok', calls[0][-1])
        self.assertNotIn('http', calls[0][-1])
        self.assertEqual(calls[1], ['open', PAGE])
        self.assertEqual(fetch.url, 'http://127.0.0.1:9/tok/model-prompt')

    def test_nothing_pending_runs_nothing(self):
        calls = []
        self.updater._announce_new_models(
            {'port': 9, 'token': 'tok'}, _run=self._run(calls),
            _urlopen=self._reply({'pending': [], 'url': None}), platform='darwin')
        self.assertEqual(calls, [])

    def test_linux_uses_the_tools_only_when_they_exist(self):
        calls = []
        reply = self._reply({'pending': [{'slug': 'a', 'name': 'A'}],
                             'url': PAGE})
        self.updater._announce_new_models({'port': 9, 'token': 'tok'},
                                          _run=self._run(calls), _urlopen=reply,
                                          _which=lambda name: None, platform='linux')
        self.assertEqual(calls, [])
        self.updater._announce_new_models({'port': 9, 'token': 'tok'},
                                          _run=self._run(calls), _urlopen=reply,
                                          _which=lambda name: '/usr/bin/' + name,
                                          platform='linux')
        self.assertEqual([cmd[0] for cmd in calls], ['notify-send', 'xdg-open'])

    def test_windows_logs_instead_of_notifying(self):
        calls = []
        reply = self._reply({'pending': [{'slug': 'a', 'name': 'A'}],
                             'url': PAGE})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.updater._announce_new_models({'port': 9, 'token': 'tok'},
                                              _run=self._run(calls), _urlopen=reply,
                                              platform='win32')
        self.assertEqual(calls, [])
        self.assertIn('new models pending: A', out.getvalue())

    def test_a_failed_announce_is_swallowed(self):
        def boom(url, timeout=None):
            raise OSError('router is not running')

        self.updater._announce_new_models({'port': 9, 'token': 'tok'},
                                          _urlopen=boom, platform='darwin')
        self.assertEqual(self.updater._pending_reply({'port': 0, 'token': 'tok'}), {})

    def test_a_reply_pointing_somewhere_else_is_not_opened(self):
        calls = []
        reply = self._reply({'pending': [{'slug': 'a', 'name': 'A'}],
                             'url': 'http://evil.example/model-prompt/x'})
        self.updater._announce_new_models({'port': 9, 'token': 'tok'},
                                          _run=self._run(calls), _urlopen=reply,
                                          platform='darwin')
        self.assertEqual([cmd[0] for cmd in calls], ['osascript'])

    def test_a_traversal_suffix_is_not_opened(self):
        calls = []
        reply = self._reply({'pending': [{'slug': 'a', 'name': 'A'}],
                             'url': 'http://127.0.0.1:9/tok/model-prompt/../../health'})
        self.updater._announce_new_models({'port': 9, 'token': 'tok'},
                                          _run=self._run(calls), _urlopen=reply,
                                          platform='darwin')
        self.assertEqual([cmd[0] for cmd in calls], ['osascript'])

    def test_a_claude_only_or_service_install_is_never_offered_codex(self):
        asked = []

        def opener(url, timeout=None):
            asked.append(url)
            raise OSError('a non-Codex install must not be asked')

        for state in ({'port': 9, 'token': 'tok', 'clients': 'claude'},
                      {'port': 9, 'token': 'tok', 'clients': 'none'},
                      {'port': 9, 'token': 'tok', 'client': 'none'}):
            calls = []
            self.updater._announce_new_models(state, _run=self._run(calls),
                                              _urlopen=opener, platform='darwin')
            self.assertEqual(calls, [])
        self.assertEqual(asked, [])

    def test_router_no_notice_silences_the_offer(self):
        asked = []

        def opener(url, timeout=None):
            asked.append(url)
            raise OSError('the notice is silenced')

        with mock.patch.dict(os.environ, {'ROUTER_NO_NOTICE': '1'}):
            self.updater._announce_new_models({'port': 9, 'token': 'tok'},
                                              _urlopen=opener, platform='darwin')
        self.assertEqual(asked, [])

    def test_the_reply_read_is_capped(self):
        sizes = []

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, size=None):
                sizes.append(size)
                return b'{"pending": [], "url": null}'

        self.updater._pending_reply({'port': 9, 'token': 'tok'},
                                    _urlopen=lambda url, timeout=None: Resp())
        self.assertEqual(sizes, [self.updater.REPLY_LIMIT])

    def test_the_loopback_fetch_ignores_a_configured_proxy(self):
        class OneShot(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({'pending': [], 'url': None}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), OneShot)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        proxy = 'http://127.0.0.1:1'  # nothing listens there
        with mock.patch.dict(os.environ, {'http_proxy': proxy,
                                          'HTTP_PROXY': proxy}):
            reply = self.updater._pending_reply({'port': server.server_port,
                                                 'token': 'tok'})
        self.assertEqual(reply, {'pending': [], 'url': None})


if __name__ == '__main__':
    unittest.main()
