"""First-run key window over loopback (Plan 047 G). No network: OpenRouter
key checks run through an injected urlopen fake."""
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock
from ai_router import key_store, setup, setup_page
from tests._platform import requires_posix_perms
from tests.setup_fixtures import offline_availability

NOW = 1_700_000_000


def _state(home, **over):
    state = {'port': 1, 'token': 'test-token', 'openai_models': [],
             'setup': {'nonce': 'n' * 16, 'expires': NOW + 900}}
    state.update(over)
    return state


def _key_ok(key='sk-test'):
    payload = json.dumps({'data': {'label': 'probe', 'limit': 10,
                                   'usage': 3}}).encode()
    assert key

    class Resp:
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def read(self, *args):
            return payload

    def fake(req, timeout=None):
        # The key must travel as a bearer header, never in the URL.
        assert req.get_header('Authorization', '').startswith('Bearer ')
        return Resp()
    return fake


def _key_rejected():
    def fake(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, 'Unauthorized', {}, None)
    return fake


class SetupUnitTests(unittest.TestCase):
    setUp = offline_availability

    def test_nonce_validation(self):
        state = _state(None)
        self.assertTrue(setup.valid_nonce(state, 'n' * 16, NOW))
        self.assertFalse(setup.valid_nonce(state, 'n' * 16, NOW + 901))
        self.assertFalse(setup.valid_nonce(state, 'wrong', NOW))
        self.assertFalse(setup.valid_nonce(state, '', NOW))
        self.assertFalse(setup.valid_nonce({'setup': {'nonce': 'n' * 16}}, 'n' * 16, NOW))
        self.assertFalse(setup.valid_nonce({}, 'n' * 16, NOW))
        self.assertFalse(setup.valid_nonce(state, '\xff', NOW))

    def test_setup_pending_moved_verbatim_into_the_state_leaf(self):
        # The boot gate depends on both spellings sharing the same expiry rules.
        from ai_router import state as state_mod
        self.assertIs(setup.setup_pending, state_mod.setup_pending)
        fresh = {'setup': {'nonce': 'n' * 16, 'expires': NOW + 60}}
        self.assertTrue(state_mod.setup_pending(fresh, NOW))
        self.assertFalse(state_mod.setup_pending(
            {'setup': {'nonce': 'n' * 16, 'expires': NOW - 1}}, NOW))
        self.assertFalse(state_mod.setup_pending(
            {'setup': {'nonce': 'n' * 16, 'expires': True}}, NOW))
        self.assertFalse(state_mod.setup_pending({}, NOW))

    def test_get_renders_form(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        status, body = setup.handle_setup(_state(home), home, 'n' * 16, False, None,
                                          _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 200)
        self.assertIn(b'<form', body)
        self.assertIn(b'n' * 16, body)

    def test_form_wiring_survives_restyle(self):
        # The page markup is styled; these attributes are the contract the
        # browser POST depends on, so a later restyle must not drop one.
        body = setup_page.form('n' * 16, 'openrouter').decode()
        self.assertIn('<form method="post" action="./' + 'n' * 16 + '">', body)
        self.assertIn('type="password" name="key" autocomplete="off"', body)
        self.assertIn('<input type="radio" name="mode" value="subscription" checked>', body)
        self.assertIn('<input type="radio" name="mode" value="none">', body)
        self.assertIn('<button type="submit">', body)
        self.assertIn('<input type="radio" name="profile" value="general" checked>', body)
        self.assertIn('<input type="radio" name="profile" value="dev">', body)
        # Inline style only: a loopback page must not fetch an external asset.
        self.assertIn('<style>', body)
        self.assertNotIn('<link', body)
        self.assertNotIn('<script', body)

    def test_unknown_link_is_404(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        status, _ = setup.handle_setup(_state(home), home, 'wrong', False, None,
                                       _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 404)

    @requires_posix_perms
    def test_post_stores_key_and_closes_setup(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state_path = home / 'mixed-router-state.json'
        state = _state(home)
        state_path.write_text(json.dumps(state))
        form = b'key=sk-test&mode=none'
        status, body = setup.handle_setup(state, home, 'n' * 16, True, form,
                                          _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 200)
        self.assertIn(b'Remaining credit', body)
        key_path = home / 'openrouter.key'
        self.assertEqual(key_path.read_text(), 'sk-test\n')
        self.assertEqual(oct(key_path.stat().st_mode & 0o777), '0o600')
        saved = json.loads(state_path.read_text())
        self.assertNotIn('setup', saved)
        self.assertEqual(saved['openai_mode'], 'none')
        self.assertEqual(saved['token'], 'test-token')
        self.assertNotIn('setup', state)

    @requires_posix_perms
    def test_json_post_reports_the_choices(self):
        # The native popup submits here (Plan 139) and renders the result
        # itself; the browser page keeps its own HTML contract.
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state = _state(home)
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        status, payload = setup.handle_setup_json(
            state, home, 'n' * 16, b'key=sk-test&mode=none&profile=dev',
            _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 200)
        self.assertEqual(payload['ok'], True)
        self.assertEqual(payload['mode'], 'none')
        self.assertEqual(payload['label'], 'probe')
        self.assertEqual(payload['limit'], 10)
        self.assertEqual(payload['usage'], 3)
        self.assertEqual((home / 'openrouter.key').read_text(), 'sk-test\n')
        self.assertNotIn('setup', json.loads(
            (home / 'mixed-router-state.json').read_text()))

    def test_json_post_reports_each_refusal(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state = _state(home)
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        status, payload = setup.handle_setup_json(
            state, home, 'wrong', b'key=sk-test', _urlopen=_key_ok(), _now=NOW)
        self.assertEqual((status, payload['ok']), (404, False))
        self.assertIn('re-run the installer', payload['error'])
        status, payload = setup.handle_setup_json(
            state, home, 'n' * 16, b'key=&mode=none', _urlopen=_key_ok(), _now=NOW)
        self.assertEqual((status, payload['ok']), (422, False))
        self.assertIn('paste a key', payload['error'])

    def test_post_with_none_mode_refreshes_picker_to_twins(self):
        # A mode flip must refresh the picker the installer already wrote.
        from ai_router.catalogue import check, external_entry
        from ai_router.registry import by_slug
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state = _state(home)
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        stale = dict(external_entry(by_slug('z-ai/glm-5.3-flash')),
                     slug='gpt-6-astra', display_name='GPT-6-Astra')
        (home / 'mixed-models.json').write_text(
            json.dumps({'models': [stale]}))
        form = b'key=sk-test&mode=none'
        status, _ = setup.handle_setup(state, home, 'n' * 16, True, form,
                                       _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 200)
        slugs = {m['slug'] for m in
                 json.loads((home / 'mixed-models.json').read_text())['models']}
        self.assertIn('openai/gpt-6-astra', slugs)
        self.assertNotIn('gpt-6-astra', slugs)
        self.assertTrue(check(str(home / 'mixed-models.json'), 'codex',
                               include_twins=True))

    def test_post_on_windows_refuses_unprotectable_key(self):
        # Windows must refuse a key whose privacy check fails after writing.
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state_path = home / 'mixed-router-state.json'
        state = _state(home)
        state_path.write_text(json.dumps(state))
        form = b'key=sk-test&mode=none'
        with mock.patch.object(setup, '_ON_WINDOWS', True), \
                mock.patch('ai_router.winacl.check',
                            side_effect=SystemExit('cannot verify')):
            status, _ = setup.handle_setup(state, home, 'n' * 16, True, form,
                                           _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 500)
        self.assertFalse((home / 'openrouter.key').exists())

    def test_post_on_windows_names_key_when_cleanup_fails(self):
        # Verify-fail plus unlink-fail must name the file with an explicit
        # delete instruction instead of a generic 500.
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state_path = home / 'mixed-router-state.json'
        state = _state(home)
        state_path.write_text(json.dumps(state))
        form = b'key=sk-test&mode=none'
        with mock.patch.object(setup, '_ON_WINDOWS', True), \
                mock.patch('ai_router.winacl.check',
                            side_effect=SystemExit('cannot verify')), \
                mock.patch.object(Path, 'unlink',
                                   side_effect=OSError('locked')):
            status, body = setup.handle_setup(state, home, 'n' * 16, True, form,
                                              _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 500)
        text = body.decode() if isinstance(body, bytes) else body
        self.assertIn('openrouter.key', text)
        self.assertIn('delete it', text)

    def test_post_rejects_bad_key_modes_and_clashes(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state = _state(home)
        status, _ = setup.handle_setup(state, home, 'n' * 16, True, b'key=&mode=none',
                                       _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 422)
        status, _ = setup.handle_setup(state, home, 'n' * 16, True,
                                       b'key=sk-test&mode=bogus',
                                       _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 422)
        status, _ = setup.handle_setup(state, home, 'n' * 16, True,
                                       b'key=sk-test&mode=subscription',
                                       _urlopen=_key_rejected(), _now=NOW)
        self.assertEqual(status, 422)
        self.assertFalse((home / 'openrouter.key').exists())

        def boom(req, timeout=None):
            raise OSError('down')
        status, _ = setup.handle_setup(state, home, 'n' * 16, True,
                                       b'key=sk-test&mode=subscription',
                                       _urlopen=boom, _now=NOW)
        self.assertEqual(status, 502)
        (home / 'openrouter.key').write_text('old\n')
        status, body = setup.handle_setup(state, home, 'n' * 16, True,
                                          b'key=sk-test&mode=subscription',
                                          _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 409)
        self.assertEqual((home / 'openrouter.key').read_text(), 'old\n')
        (home / 'openrouter.key').write_bytes(b'\xff\xfe\x00b')
        status, _ = setup.handle_setup(state, home, 'n' * 16, True,
                                       b'key=sk-test&mode=subscription',
                                       _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 409)
        self.assertEqual((home / 'openrouter.key').read_bytes(), b'\xff\xfe\x00b')

    @requires_posix_perms
    def test_post_claims_empty_installer_placeholder(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state = _state(home)
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        (home / 'openrouter.key').write_text('')
        status, _ = setup.handle_setup(state, home, 'n' * 16, True,
                                       b'key=sk-test&mode=subscription',
                                       _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 200)
        self.assertEqual((home / 'openrouter.key').read_text(), 'sk-test\n')
        self.assertEqual(oct((home / 'openrouter.key').stat().st_mode & 0o777), '0o600')

    def test_load_state_boots_keyless_on_fresh_nonce(self):
        import time as _time
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        path = home / 'mixed-router-state.json'
        with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': ''}):
            with mock.patch('ai_router.runtime.ROUTER_HOME', home):
                from ai_router.runtime import load_state as load
                fresh = _state(home)
                fresh['token'] = 'test-token'.ljust(32, 'x')
                fresh['setup']['expires'] = int(_time.time()) + 900
                path.write_text(json.dumps(fresh))
                self.assertEqual(load(path)['token'], 'test-token'.ljust(32, 'x'))
                fresh['setup']['expires'] = int(_time.time()) - 1
                path.write_text(json.dumps(fresh))
                with self.assertRaisesRegex(SystemExit, 'credential problem'):
                    load(path)

class KeyWindowTests(unittest.TestCase):
    setUp = offline_availability
    # Plan 107 Stage 3: keyless boot, first-use window, revoked-key carve-out.
    def _home(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        return home

    def _dead_fetch(self, status):
        def fake(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, status, 'Denied', {}, None)
        return fake

    def _post_with_stored(self, stored_text, live):
        home = self._home()
        state = _state(home)
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        (home / 'openrouter.key').write_text(stored_text)
        os.chmod(home / 'openrouter.key', 0o600)
        form = b'key=sk-test&mode=none'
        with mock.patch.object(setup, '_ON_WINDOWS', False), \
                mock.patch.object(key_store, '_stored_key_live', return_value=live):
            status, body = setup.handle_setup(
                state, home, 'n' * 16, True, form, _urlopen=_key_ok(), _now=NOW)
        return home, status, body

    def test_post_replaces_key_proven_dead_on_401(self):
        home, status, _ = self._post_with_stored('sk-dead\n', False)
        self.assertEqual(status, 200)
        self.assertEqual((home / 'openrouter.key').read_text(), 'sk-test\n')

    def test_post_refuses_live_key_without_explicit_delete(self):
        home, status, _ = self._post_with_stored('sk-live\n', True)
        self.assertEqual(status, 409)
        self.assertEqual((home / 'openrouter.key').read_text(), 'sk-live\n')

    def test_post_refuses_truncate_when_stored_check_errors(self):
        home, status, _ = self._post_with_stored('sk-maybe\n', True)
        self.assertEqual(status, 409)
        self.assertEqual((home / 'openrouter.key').read_text(), 'sk-maybe\n')

    def test_stored_key_live_false_only_on_401_or_403(self):
        self.assertFalse(key_store._stored_key_live('openrouter', 'sk-x', self._dead_fetch(401)))
        self.assertFalse(key_store._stored_key_live('openrouter', 'sk-x', self._dead_fetch(403)))
        self.assertTrue(key_store._stored_key_live('openrouter', 'sk-x', self._dead_fetch(429)))
        self.assertTrue(key_store._stored_key_live('openrouter', 'sk-x', _key_ok()))
        def boom(req, timeout=None):
            raise OSError('down')
        self.assertTrue(key_store._stored_key_live('openrouter', 'sk-x', boom))

    def test_open_key_window_mints_once_and_reuses_live_nonce(self):
        home = self._home()
        (home / 'mixed-router-state.json').write_text(json.dumps({'port': 1, 'token': 't'}))
        server = mock.Mock()
        server.lock = threading.Lock()
        server.state = {'port': 1, 'token': 't'}
        opened = []
        started = []
        prompt = lambda url, **kw: started.append(url) or True  # noqa: E731
        self.assertTrue(setup.open_key_window(server, home, _opener=opened.append,
                                              _prompt=prompt))
        first = server.state['setup']['nonce']
        self.assertTrue(setup.open_key_window(server, home, _opener=opened.append,
                                              _prompt=prompt))
        self.assertEqual(server.state['setup']['nonce'], first)
        self.assertEqual(len(started), 1)
        self.assertEqual(opened, [], 'the popup replaces the browser window')
        saved = json.loads((home / 'mixed-router-state.json').read_text())
        self.assertEqual(saved['setup']['nonce'], first)

    def test_open_key_window_never_prints_url_off_tty(self):
        home = self._home()
        (home / 'mixed-router-state.json').write_text(json.dumps({'port': 1, 'token': 't'}))
        server = mock.Mock()
        server.lock = threading.Lock()
        server.state = {'port': 1, 'token': 't'}
        buf = io.StringIO()
        with mock.patch.object(setup.sys.stdout, 'isatty', return_value=False):
            with mock.patch('ai_router.setup.log_event') as logged:
                import contextlib as _ctx
                with _ctx.redirect_stdout(buf):
                    setup.open_key_window(server, home, _opener=lambda url: True,
                                          _prompt=lambda url, **kw: True)
        self.assertNotIn(server.state['setup']['nonce'], buf.getvalue())
        self.assertNotIn('test-token', buf.getvalue())
        logged.assert_called_once()
        self.assertNotIn('test-token', str(logged.call_args))

    def test_open_key_window_keeps_the_browser_opener_out_of_the_post(self):
        # The popup's POST seam must not be the browser opener: the router
        # path broke when webbrowser.open was reused as a urlopen-shaped seam.
        home = self._home()
        (home / 'mixed-router-state.json').write_text(json.dumps({'port': 1, 'token': 't'}))
        server = mock.Mock()
        server.lock = threading.Lock()
        server.state = {'port': 1, 'token': 't'}
        seen = {}
        opener = object()

        def prompt(url, **kwargs):
            seen.update(kwargs)
            return True

        self.assertTrue(setup.open_key_window(server, home, _opener=opener,
                                              _prompt=prompt))
        self.assertIs(seen['opener'], opener)
        self.assertNotIn('post', seen)


    def test_atomic_replace_recovers_from_stale_tmp(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        path = home / 'mixed-router-state.json'
        path.write_text(json.dumps({'port': 1, 'token': 't'}))
        stale = path.with_name(path.name + '.setup.tmp')
        stale.write_text('crash residue')
        setup._atomic_replace(path, {'port': 1, 'token': 't', 'setup': {'nonce': 'x', 'expires': 1}})
        self.assertEqual(json.loads(path.read_text())['setup']['nonce'], 'x')
        self.assertFalse(stale.exists())
