"""The dialog-only new-model offer fired by the updater.

The updater discovers pending model names, stages the shared restart notice,
and hands it to the native dialog owner. It never opens a browser page or
starts a separate desktop notification.
"""
import http.server
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.install_fixtures import install_mod


class AnnounceTests(unittest.TestCase):
    """A model notice is one native dialog and never disturbs an update."""

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

    def _announce(self, home, state, reply):
        record = mock.Mock()
        show = mock.Mock()
        with mock.patch.object(self.updater._svc, 'current_version',
                               return_value='9.9.9'), \
                mock.patch.object(self.updater._svc.notice, 'record', record), \
                mock.patch.object(self.updater._svc.notice, 'show_pending', show):
            self.updater._announce_new_models(home, state, _urlopen=reply)
        return record, show

    def test_new_models_show_one_dialog_without_opening_the_page(self):
        reply = self._reply({
            'pending': [{'slug': 'a', 'name': 'A'},
                        {'slug': 'b', 'name': 'B'},
                        {'slug': 'c', 'name': 'C'},
                        {'slug': 'd', 'name': 'D'}],
            'url': 'http://evil.example/model-prompt/not-used'})
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            record, show = self._announce(
                home, {'port': 9, 'token': 'tok'}, reply)
        names = ['A', 'B', 'C', '+1 more']
        record.assert_called_once_with(
            home, '9.9.9', '9.9.9', None, names=names)
        show.assert_called_once_with(home, names=names)
        self.assertEqual(reply.url, 'http://127.0.0.1:9/tok/model-prompt')

    def test_nothing_pending_runs_no_dialog(self):
        with tempfile.TemporaryDirectory() as tmp:
            record, show = self._announce(
                Path(tmp), {'port': 9, 'token': 'tok'},
                self._reply({'pending': [], 'url': None}))
        record.assert_not_called()
        show.assert_not_called()

    def test_a_claude_only_or_service_install_is_not_asked_about_codex(self):
        def opener(url, timeout=None):
            raise OSError('a non-Codex install must not be asked')

        for state in ({'port': 9, 'token': 'tok', 'clients': 'claude'},
                      {'port': 9, 'token': 'tok', 'clients': 'none'},
                      {'port': 9, 'token': 'tok', 'client': 'none'}):
            with tempfile.TemporaryDirectory() as tmp:
                record, show = self._announce(Path(tmp), state, opener)
            record.assert_not_called()
            show.assert_not_called()

    def test_router_no_notice_silences_the_offer(self):
        def opener(url, timeout=None):
            raise OSError('the notice is silenced')

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {'ROUTER_NO_NOTICE': '1'}):
            record, show = self._announce(
                Path(tmp), {'port': 9, 'token': 'tok'}, opener)
        record.assert_not_called()
        show.assert_not_called()

    def test_a_failed_announce_is_swallowed(self):
        def boom(url, timeout=None):
            raise OSError('router is not running')

        with tempfile.TemporaryDirectory() as tmp:
            self.updater._announce_new_models(
                Path(tmp), {'port': 9, 'token': 'tok'}, _urlopen=boom)

    def test_named_model_state_stays_quiet_until_the_names_change(self):
        notice = self.updater._svc.notice
        first = ['Z.ai: GLM 5.3 Flash']
        changed = first + ['Xiaomi: MiMo V2.6 Flash']
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertTrue(notice.record(
                home, '1.0.1', '1.0.1', names=first))
            self.assertFalse(notice.record(
                home, '1.0.1', '1.0.1', names=first))
            with mock.patch.object(notice, 'dialog_command',
                                   return_value=['fake-dialog']), \
                    mock.patch.object(notice, '_dialog_up', return_value=True):
                notice.show_pending(
                    home, spawn=lambda cmd: 42,
                    pid_alive=lambda pid: True, names=first)
            self.assertFalse(notice.record(
                home, '1.0.1', '1.0.1', names=first))
            self.assertTrue(notice.record(
                home, '1.0.1', '1.0.1', names=changed))
            doc = json.loads((home / 'update-notice.json').read_text())
            self.assertEqual(doc['names'], changed)
            self.assertNotIn('shown', doc)

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
