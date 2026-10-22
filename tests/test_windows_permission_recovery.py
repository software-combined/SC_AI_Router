"""Request-time permission failures are local, bounded and recoverable."""
import concurrent.futures
import itertools
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_router import credentials, errors, winacl
from tests.fakes import FakeUpstream, install_fake
from tests.harness import post, start_server

SID = 'S-1-5-21-1-2-3-1001'
ACL = dict(user=SID, owner=SID, dacl=True,
           rules=[dict(sid=SID, type=0, mask=2032127, flags=0)])


class PermissionRecoveryTests(unittest.TestCase):
    def test_http_retry_recovers_and_fifteen_cold_requests_complete(self):
        install_fake(self, lambda *args: FakeUpstream(200, json.dumps({
            'id': 'synthetic', 'choices': [{'message': {'role': 'assistant', 'content': 'ok'},
                                          'finish_reason': 'stop'}]}).encode()))
        query = mock.Mock(side_effect=itertools.chain(
            [OSError(5, 'synthetic'), OSError(5, 'synthetic')], itertools.repeat(ACL)))
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.dict('os.environ', {}, clear=True), \
                mock.patch.object(credentials, '_ON_WINDOWS', True), \
                mock.patch.object(winacl._native, 'query', query), \
                mock.patch('ai_router.setup.open_key_window') as key_window:
            home = Path(temporary)
            (home / 'openrouter.key').write_text('synthetic-key')
            server = start_server({'port': 0, 'token': 'test-token', 'openai_models': []},
                                  credentials=credentials.Credentials({}, home, {}))
            try:
                def request(_):
                    response = post(server.server_port, '/test-token/responses',
                                    {'model': 'z-ai/glm-5.3', 'input': 'hi'})
                    body = json.loads(response.read())
                    return response.status, response.getheader('Retry-After'), body
                status, retry, body = request(0)
                self.assertEqual((status, retry), (503, '1'))
                self.assertEqual(body['error']['code'], 'CREDENTIAL_CHECK_UNAVAILABLE')
                with concurrent.futures.ThreadPoolExecutor(max_workers=15) as workers:
                    results = list(workers.map(request, range(15)))
                self.assertEqual([result[0] for result in results], [200] * 15)
                key_window.assert_not_called()
            finally:
                server.shutdown()
                server.server_close()

    def test_query_failure_is_retried_once_without_caching(self):
        query = mock.Mock(side_effect=[OSError(5, 'synthetic'), ACL])
        winacl.check('synthetic.key', query=query)
        self.assertEqual(query.call_count, 2)
        winacl.check('synthetic.key', query=lambda path: ACL)

    def test_unavailable_verification_keeps_the_permission_error_contract(self):
        path = Path('synthetic.key')
        with mock.patch.object(winacl._native, 'query', side_effect=OSError(5, 'synthetic')):
            with self.assertRaises(PermissionError) as caught:
                winacl.require_owner_only(path, windows=True)
            self.assertIsInstance(caught.exception, winacl.VerificationUnavailable)
            with mock.patch('os.name', 'nt'):
                self.assertIs(winacl.owner_only(path), False)

    def test_query_failure_during_sharing_reopens_the_closed_app(self):
        from tests.test_claude_desktop_switch import SwitchTests, switcher
        case = SwitchTests('test_round_trip_changes_only_mode_and_preserves_receipts_and_sessions')
        self.addCleanup(case.doCleanups)
        case.setUp()
        case.sync.side_effect = lambda *_: winacl.require_owner_only(Path('synthetic.key'), windows=True)
        with mock.patch.object(winacl._native, 'query', side_effect=OSError(5, 'synthetic')):
            with self.assertRaises(switcher.SwitchError):
                case.switch()
        self.assertEqual(case.run.call_args.args[0], ['/usr/bin/open', '-b', switcher.BUNDLE_ID])

    def test_unavailable_check_maps_to_retryable_failure(self):
        query = mock.Mock(side_effect=OSError(5, 'synthetic'))
        with mock.patch.object(winacl._native, 'query', query), \
                mock.patch.object(credentials, '_ON_WINDOWS', True), \
                mock.patch.object(Path, 'exists', return_value=True):
            with self.assertRaises(errors.CredentialCheckUnavailable) as caught:
                credentials.Credentials({}, Path('/synthetic'), {}).key_for()
        result = errors.map_client_error(caught.exception)
        self.assertEqual((result.status, result.code), (503, 'CREDENTIAL_CHECK_UNAVAILABLE'))
        self.assertEqual(result.retry_after, '1')
        self.assertNotIn('enter', result.message)
        self.assertEqual(query.call_count, 2)

    def test_fifteen_cold_checks_start_no_subprocess(self):
        with mock.patch.object(winacl._native, 'query', return_value=ACL), \
                mock.patch('subprocess.run', side_effect=AssertionError('no process')):
            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as workers:
                list(workers.map(winacl.check, ['synthetic.key'] * 15))

    def test_permission_change_is_visible_on_the_next_check(self):
        query = mock.Mock(side_effect=[ACL, dict(ACL, rules=[
            dict(sid='S-1-1-0', type=0, mask=2032127, flags=0)])])
        winacl.check('synthetic.key', query=query)
        with self.assertRaisesRegex(SystemExit, 'readable by'):
            winacl.check('synthetic.key', query=query)
