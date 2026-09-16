import http.client
import json
import logging
import logging.handlers
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from ai_router.credentials import Credentials
from ai_router.runtime import LOG, load_state
from tests._platform import requires_posix_perms
from tests.fakes import FakeUpstream, install_fake
from tests.harness import (
    start_auth_server as _start_auth_server,
    start_server as _start_server,
    test_state as _test_state,
)

TOKEN = 't' * 32


def _capture_log(test):
    log = tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False)
    log.close()
    test.addCleanup(os.unlink, log.name)
    handler = logging.handlers.RotatingFileHandler(log.name, maxBytes=1024 * 1024, backupCount=1)
    old_level = LOG.level
    LOG.setLevel(logging.INFO)
    test.addCleanup(LOG.setLevel, old_level)
    LOG.addHandler(handler)
    test.addCleanup(LOG.removeHandler, handler)
    test.addCleanup(handler.close)
    return log.name, handler


class LoadStateTests(unittest.TestCase):
    def _write(self, obj):
        f = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
        json.dump(obj, f)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def _auth(self, payload):
        """The client's own auth file under a temp HOME: (path, env)."""
        env_home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(env_home), True)
        auth = env_home / '.local' / 'share' / 'opencode' / 'auth.json'
        auth.parent.mkdir(parents=True)
        if payload is not None:
            auth.write_text(payload if isinstance(payload, str) else json.dumps(payload))
        return auth, {'HOME': str(env_home)}

    def test_load_state_refuses_a_weak_token(self):
        for name, token in (('short', 't' * 31), ('bad-char', '!' * 32),
                            ('empty', '')):
            with self.subTest(name=name):
                path = self._write({'port': 0, 'token': token, 'openai_models': []})
                with self.assertRaises(SystemExit) as ctx:
                    load_state(Path(path))
                message = str(ctx.exception)
                self.assertIn('token is too weak', message)
                if token:
                    self.assertNotIn(token, message)

    def test_load_state_accepts_a_strong_token(self):
        path = self._write({'port': 0, 'token': TOKEN, 'openai_models': []})
        with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'sk-or'}):
            self.assertEqual(load_state(Path(path))['token'], TOKEN)

    def test_load_state_reports_missing_keys(self):
        path = self._write({'port': 1})
        with self.assertRaises(SystemExit) as ctx:
            load_state(Path(path))
        for key in ('token', 'openai_models'):
            self.assertIn(key, str(ctx.exception))

    def test_load_state_reports_an_unreadable_path_as_such(self):
        # A state path that exists but cannot be read is not a missing file;
        # the operator must not be sent looking for a file that is right there.
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = Path(tmp) / 'state-dir'
        path.mkdir()
        with self.assertRaises(SystemExit) as ctx:
            load_state(path)
        self.assertIn('could not be read', str(ctx.exception))
        self.assertIn(str(path), str(ctx.exception))

    def test_load_state_rejects_unusable_credential_file(self):
        for name, payload in (
                ('missing', None),
                ('non-api', {'openrouter': {'type': 'other', 'key': 'k'}}),
                ('corrupt', 'not-json{{{'),
                ('empty-object', {}),
                ('api-without-key', {'openrouter': {'type': 'api'}}),
                ('null-entry', {'openrouter': None})):
            with self.subTest(name=name):
                auth, env = self._auth(payload)
                path = self._write({'port': 0, 'token': TOKEN, 'openai_models': [],
                                    'opencode_auth': str(auth)})
                # Isolate the key-file leg: on machines where the router is
                # installed, the real ~/.codex/mixed-model-router/openrouter.key
                # otherwise satisfies the lookup before opencode_auth is read.
                home = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, str(home), True)
                with mock.patch('ai_router.runtime.ROUTER_HOME', home), \
                        mock.patch.dict(os.environ, env, clear=True):
                    with self.assertRaises(SystemExit) as ctx:
                        load_state(Path(path))
                self.assertIn('OpenRouter credential problem', str(ctx.exception))

    def test_load_state_accepts_valid_file(self):
        auth, env = self._auth({'openrouter': {'type': 'api', 'key': 'k'}})
        path = self._write({'port': 0, 'token': TOKEN, 'openai_models': [],
                            'opencode_auth': str(auth)})
        # Isolate ROUTER_HOME: on a machine where the router is installed, the
        # real ~/.codex/mixed-model-router/openrouter.key is read before the
        # opencode_auth key here and can fail the lookup closed.
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(home), True)
        with mock.patch('ai_router.runtime.ROUTER_HOME', home), \
                mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(load_state(Path(path))['token'], TOKEN)

    def test_load_state_without_opencode_auth_needs_env_or_key_file(self):
        path = self._write({'port': 0, 'token': TOKEN, 'openai_models': []})
        with mock.patch.dict(os.environ):
            os.environ.pop('OPENROUTER_API_KEY', None)
            home = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, str(home), True)
            with mock.patch('ai_router.runtime.ROUTER_HOME', home):
                with self.assertRaises(SystemExit) as ctx:
                    load_state(Path(path))
                self.assertIn('OpenRouter credential problem', str(ctx.exception))

    def test_one_resolvable_external_key_boots_while_another_stays_keyless(self):
        # Plan 141: a registry with rows for more than one external provider
        # boots as soon as one key resolves, and the keyless provider fails
        # its own requests closed instead of taking the service down.
        from ai_router import provider_defs
        acme = provider_defs.ProviderDef(
            id='acme', label='Acme', kind=provider_defs.EXTERNAL,
            host='acme.example', responses_path='/v1',
            key=provider_defs.KeySpec('ACME_API_KEY', 'acme.key'),
            dialect='acme')
        provider_defs.PROVIDERS = provider_defs.PROVIDERS + (acme,)
        provider_defs.BY_ID = {p.id: p for p in provider_defs.PROVIDERS}
        def restore():
            provider_defs.PROVIDERS = tuple(
                p for p in provider_defs.PROVIDERS if p.id != 'acme')
            provider_defs.BY_ID = {p.id: p for p in provider_defs.PROVIDERS}
        self.addCleanup(restore)

        import ai_router.registry as registry
        rows = list(registry.MODELS) + [
            registry.Model(slug='acme/one', provider='acme', display_name='Acme: One',
                           vendor='Acme', reasoning=('low',),
                           default_reasoning='low')]
        with mock.patch.object(registry, 'MODELS', rows):
            path = self._write({'port': 0, 'token': TOKEN, 'openai_models': []})
            home = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, str(home), True)
            (home / 'openrouter.key').write_text('sk-or\n')
            os.chmod(home / 'openrouter.key', 0o600)
            with mock.patch.dict(os.environ, clear=True), \
                    mock.patch('ai_router.runtime.ROUTER_HOME', home):
                # One provider resolves, so the router boots.
                self.assertEqual(load_state(Path(path))['token'], TOKEN)
                # The keyless provider is named, and its own request fails closed.
                credentials = Credentials({'openai_models': []}, home, {})
                self.assertEqual(credentials.key_for('openrouter'), 'sk-or')
                self.assertIsInstance(credentials.key_missing('acme'), LookupError)


class CredentialRequestMappingTests(unittest.TestCase):

    @requires_posix_perms
    def test_a_widened_key_file_401_body_carries_no_path(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(home), True)
        key = home / 'openrouter.key'
        key.write_text('sk-live\n')
        os.chmod(key, 0o644)
        with mock.patch.dict(os.environ):
            os.environ.pop('OPENROUTER_API_KEY', None)
            server = self._server_without_opencode(home)
            response = self._post(server, {'model': 'z-ai/glm-5.3', 'input': []})
            body = json.loads(response.read())
        self.assertEqual(response.status, 401)
        self.assertEqual(body['error']['code'], 'CREDENTIAL_PERMISSION')
        self.assertIn('[path]', body['error']['message'])
        self.assertIn('readable by the owner only', body['error']['message'])
        self.assertNotIn(str(home), body['error']['message'])

    def _server_without_opencode(self, home):
        state = _test_state('/nonexistent-auth.json')
        del state['opencode_auth']
        # Real Credentials against the temp home: this is the point of the
        # test. test-key stubs would mask the key-file/env mapping.
        server = _start_server(state, credentials=Credentials(state, home, env=os.environ))
        self.addCleanup(server.shutdown)
        return server

    def _post(self, server, payload):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('POST', '/test-token/responses', body=json.dumps(payload),
                     headers={'Content-Type': 'application/json'})
        return conn.getresponse()

    def test_empty_key_file_maps_to_400(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(home), True)
        (home / 'openrouter.key').write_text('\n')
        os.chmod(home / 'openrouter.key', 0o600)
        with mock.patch.dict(os.environ):
            os.environ.pop('OPENROUTER_API_KEY', None)
            server = self._server_without_opencode(home)
            response = self._post(server, {'model': 'z-ai/glm-5.3', 'input': []})
            self.assertEqual(response.status, 400)

    def test_nothing_configured_maps_to_400(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(home), True)
        with mock.patch.dict(os.environ):
            os.environ.pop('OPENROUTER_API_KEY', None)
            server = self._server_without_opencode(home)
            response = self._post(server, {'model': 'z-ai/glm-5.3', 'input': []})
            self.assertEqual(response.status, 400)
            message = json.loads(response.read())['error']['message']
        self.assertIn('No OpenRouter key', message)
        self.assertNotIn(str(home), message)


class LoggingAndHealthTests(unittest.TestCase):
    def _server(self):
        return _start_auth_server(self)

    def test_rejections_are_logged_with_timestamp(self):
        log_name, handler = _capture_log(self)
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('GET', '/wrong-token/health')
        self.assertEqual(conn.getresponse().status, 403)
        handler.flush()
        lines = [json.loads(line) for line in open(log_name) if line.strip()]
        rejected = [e for e in lines if e.get('event') == 'request_rejected']
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]['status'], 403)
        datetime.fromisoformat(rejected[0]['ts'])
        self.assertNotIn('test-token', open(log_name).read())
        self.assertNotIn('wrong-token', open(log_name).read())

    def test_authorized_rejection_logs_stripped_path_without_token(self):
        log_name, handler = _capture_log(self)
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('GET', '/test-token/secret-path?x=1')
        self.assertEqual(conn.getresponse().status, 404)
        handler.flush()
        lines = [json.loads(line) for line in open(log_name) if line.strip()]
        rejected = [e for e in lines if e.get('event') == 'request_rejected']
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]['path'], '/secret-path')
        self.assertNotIn('test-token', open(log_name).read())

    def test_provider_selected_logged_only_with_debug_flag(self):
        install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))
        for flag, expected in (({}, 0), ({'ROUTER_DEBUG': '1'}, 1)):
            with self.subTest(flag=flag):
                log_name, handler = _capture_log(self)
                server = self._server()
                with mock.patch.dict(os.environ, flag):
                    if 'ROUTER_DEBUG' not in flag:
                        os.environ.pop('ROUTER_DEBUG', None)
                    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
                    conn.request('POST', '/test-token/responses',
                                 body=json.dumps({'model': 'z-ai/glm-5.3', 'input': []}),
                                 headers={'Content-Type': 'application/json'})
                    self.assertEqual(conn.getresponse().status, 200)
                handler.flush()
                lines = [json.loads(line) for line in open(log_name) if line.strip()]
                selected = [e for e in lines if e.get('event') == 'provider_selected']
                self.assertEqual(len(selected), expected)
                for event in selected:
                    self.assertEqual(event['provider'], 'openrouter')
                    self.assertNotIn('Authorization', json.dumps(event))

    def test_transport_error_carries_type_not_text(self):
        def boom(*a, **k):
            raise OSError('reset by peer')
        install_fake(self, boom)
        log_name, handler = _capture_log(self)
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('POST', '/test-token/responses',
                     body=json.dumps({'model': 'z-ai/glm-5.3', 'input': []}),
                     headers={'Content-Type': 'application/json',
                              'Authorization': 'Bearer subscription-secret'})
        self.assertEqual(conn.getresponse().status, 502)
        handler.flush()
        text = open(log_name).read()
        lines = [json.loads(line) for line in text.splitlines() if line.strip()]
        errors = [e for e in lines if e.get('event') == 'transport_error']
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['error_type'], 'OSError')
        self.assertNotIn('traceback', errors[0])
        self.assertNotIn('reset by peer', text)
        self.assertNotIn('Bearer', text)
        self.assertNotIn('test-key', text)

    def test_health_reports_version_and_inflight(self):
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('GET', '/test-token/health')
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        body = json.loads(response.read())
        self.assertEqual(body['status'], 'ok')
        self.assertIsInstance(body['version'], str)
        self.assertEqual(body['inflight'], 0)

if __name__ == '__main__':
    unittest.main()
