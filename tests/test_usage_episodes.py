"""ChatGPT usage-limit episodes recorded for Codex desktop (Switch Codex E1).

The Express job reads `codex-usage-limit.json` to offer Switch Codex once per
episode. These pin what opens one (a Codex desktop 429 naming
`usage_limit_reached`, the refusal Codex itself reads as a spent allowance),
what never does (a CLI request, a transient 429), that repeats stay one
episode, that an ended one gives way to the next, and that the file never
carries request content or changes the turn's answer.
"""
import json
import os
import stat
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from ai_router import usage_episodes
from tests.fakes import FakeUpstream, install_fake
from tests.harness import auth_file, post, start_server, test_state, tmp_home

# The User-Agent the app-server bundled with Codex desktop 26.924.22138 sends
# (`get_codex_user_agent`, suffix from the desktop's initialize client info),
# and the CLI's, whose embedded app-server names itself `codex-tui`.
DESKTOP = ('Codex Desktop/0.158.0-alpha.2.1 (Mac OS 26.5.0; arm64) unknown '
           '(Codex Desktop; 26.924.22138)')
CLI = ('codex-tui/0.158.0-alpha.2.1 (Mac OS 26.5.0; arm64) iTerm.app/3.5.0 '
       '(codex-tui; 0.158.0-alpha.2.1)')
MODEL = 'gpt-6-luna'
T0 = 1_790_000_000
FIELDS = {'seen_at', 'resets_at', 'client_version'}


def limit_body(resets_at=None, **extra):
    """The 429 body Codex's own client test uses for a spent allowance."""
    error = {'type': 'usage_limit_reached', 'message': 'limit reached',
             'plan_type': 'pro', **extra}
    if resets_at is not None:
        error['resets_at'] = resets_at
    return json.dumps({'error': error}).encode()


def seconds(stamp):
    return datetime.fromisoformat(stamp).timestamp()


def record(home, body, now, agent=DESKTOP, provider='openai'):
    handler = SimpleNamespace(server=SimpleNamespace(credentials=SimpleNamespace(home=home)))
    prepared = SimpleNamespace(provider=provider, headers={'User-Agent': agent})
    usage_episodes.record(handler, prepared, body, now=now)


class _HomeCredentials:
    """The credential surface the handler reads, with a router home."""

    def __init__(self, home):
        self.home = home

    def key_for(self, provider_id=None):
        return 'test-key'


class RefusedTurnTests(unittest.TestCase):
    def _turn(self, home, body, agent=DESKTOP, headers=None, payload=None):
        """(status, Retry-After, body) of one ChatGPT turn refused with `body`."""
        install_fake(self, lambda: FakeUpstream(
            429, body, [('Content-Type', 'application/json')]))
        state = test_state(auth_file(self))
        state['openai_models'] = [MODEL]
        server = start_server(state, credentials=_HomeCredentials(home))
        self.addCleanup(server.shutdown)
        response = post(server.server_port, '/test-token/responses',
                        {'model': MODEL, 'input': [], **(payload or {})},
                        {'User-Agent': agent, **(headers or {})})
        return response.status, response.getheader('Retry-After'), response.read()

    def test_a_desktop_usage_limit_refusal_writes_the_record(self):
        home, resets = tmp_home(self), int(time.time()) + 3 * 3600
        before = time.time()
        status, _, _ = self._turn(home, limit_body(resets))
        self.assertEqual(status, 503)
        doc = json.loads(usage_episodes.path(home).read_text())
        self.assertEqual(set(doc), FIELDS)
        self.assertEqual(doc, usage_episodes.current(home))
        self.assertEqual(doc['client_version'], '26.924.22138')
        self.assertTrue(doc['seen_at'].endswith('+00:00'))
        self.assertTrue(before - 1 <= seconds(doc['seen_at']) <= time.time())
        self.assertEqual(seconds(doc['resets_at']), resets)
        if os.name != 'nt':
            mode = stat.S_IMODE(os.stat(usage_episodes.path(home)).st_mode)
            self.assertEqual(mode, 0o600)

    def test_cli_and_transient_refusals_leave_no_record(self):
        spent = limit_body(int(time.time()) + 3600)
        cases = (('CLI', CLI, spent),
                 ('transient', DESKTOP, json.dumps({'error': {
                     'type': 'rate_limit_exceeded', 'message': 'slow down'}}).encode()),
                 ('empty', DESKTOP, b'{}'),
                 ('unreadable', DESKTOP, b'<html>slow down</html>'))
        for name, agent, body in cases:
            with self.subTest(name):
                home = tmp_home(self)
                self.assertEqual(self._turn(home, body, agent)[0], 503)
                self.assertFalse(usage_episodes.path(home).exists())

    def test_request_and_account_text_never_reach_the_file(self):
        home, marker = tmp_home(self), 'MARKER-7f3a'
        secret, email = 'sk-or-v1-' + 'q' * 32, 'person@example.com'
        text = f'{marker} {secret} {email}'
        payload = {'instructions': text, 'input': [{'role': 'user', 'content': [
            {'type': 'input_text', 'text': text}]}],
            'tools': [{'type': 'function', 'name': 'tool_' + marker}]}
        headers = {'Authorization': 'Bearer ' + 'e' * 40,
                   'ChatGPT-Account-Id': 'acct-' + marker, 'originator': 'Codex Desktop'}
        agent = DESKTOP.replace('unknown', email).replace('22138)', f'22138-{marker})')
        body = limit_body(int(time.time()) + 3600, message=text,
                          account_id='acct-' + marker, email=email)
        self._turn(home, body, agent, headers, payload)
        written = usage_episodes.path(home).read_text()
        self.assertEqual(set(json.loads(written)), FIELDS)
        self.assertEqual(json.loads(written)['client_version'], '26.924.22138')
        for leak in (marker, secret, email, 'acct', 'Bearer', 'test-token', 'pro'):
            self.assertNotIn(leak, written)

    def test_a_failing_write_leaves_the_answer_unchanged(self):
        body = limit_body(int(time.time()) + 3600)
        expected = self._turn(tmp_home(self), body)
        home = tmp_home(self)
        with mock.patch.object(usage_episodes, 'replace_json',
                               side_effect=OSError('disk full')), \
                mock.patch.object(usage_episodes, 'log_event') as log:
            self.assertEqual(self._turn(home, body), expected)
        self.assertEqual(expected[:2], (503, '2'))
        self.assertFalse(usage_episodes.path(home).exists())
        log.assert_called_once_with('usage_episode_failed', reason='OSError')


class EpisodeTests(unittest.TestCase):
    def test_repeats_keep_one_episode_and_only_refine_the_reset(self):
        home = tmp_home(self)
        record(home, limit_body(T0 + 3600), T0)
        first = usage_episodes.current(home)
        record(home, limit_body(T0 + 3600), T0 + 60)
        self.assertEqual(usage_episodes.current(home), first)
        record(home, limit_body(T0 + 7200), T0 + 120,
               agent=DESKTOP.replace('26.924.22138', '26.930.1'))
        refined = usage_episodes.current(home)
        self.assertEqual(refined, dict(first, resets_at=refined['resets_at']))
        self.assertEqual(seconds(refined['resets_at']), T0 + 7200)
        record(home, limit_body(), T0 + 180)
        self.assertEqual(usage_episodes.current(home), refined)
        # Without a named reset the episode holds for the bounded window.
        home = tmp_home(self)
        record(home, limit_body(), T0)
        record(home, limit_body(), T0 + usage_episodes.WINDOW_S - 1)
        self.assertEqual(seconds(usage_episodes.current(home)['seen_at']), T0)

    def test_an_ended_episode_starts_a_new_one(self):
        home = tmp_home(self)
        record(home, limit_body(T0 + 3600), T0)
        record(home, limit_body(), T0 + 3600)
        episode = usage_episodes.current(home)
        self.assertEqual(seconds(episode['seen_at']), T0 + 3600)
        self.assertIsNone(episode['resets_at'])
        later = T0 + 3600 + usage_episodes.WINDOW_S
        record(home, limit_body(later + 60), later)
        episode = usage_episodes.current(home)
        self.assertEqual(seconds(episode['seen_at']), later)
        self.assertEqual(seconds(episode['resets_at']), later + 60)

    def test_an_implausible_reset_is_recorded_as_unnamed(self):
        for reset in (T0 - 1, T0 + usage_episodes.MAX_RESET_S + 1, True, 'soon'):
            with self.subTest(reset=reset):
                home = tmp_home(self)
                record(home, limit_body(reset), T0)
                self.assertEqual(usage_episodes.current(home)['resets_at'], None)

    def test_an_external_or_unknown_client_refusal_leaves_no_record(self):
        for provider, agent in (('openrouter', DESKTOP), ('openai', None),
                                ('openai', 'Codex Desktop/0.158.0 (Mac OS 26.5.0; arm64)')):
            with self.subTest(provider=provider, agent=agent):
                home = tmp_home(self)
                record(home, limit_body(T0 + 3600), T0, agent=agent, provider=provider)
                self.assertFalse(usage_episodes.path(home).exists())

    def test_a_corrupt_or_missing_file_reads_as_no_episode(self):
        home = tmp_home(self)
        self.assertIsNone(usage_episodes.current(home))
        stamp = '2026-09-29T05:00:00+00:00'
        for text in ('not json', '[]', '{"seen_at": "yesterday"}',
                     '{"seen_at": "2026-09-29T05:00:00"}',
                     json.dumps({'seen_at': stamp, 'resets_at': 17}),
                     json.dumps({'seen_at': stamp, 'client_version': '26.924 beta'})):
            with self.subTest(text=text):
                usage_episodes.path(home).write_text(text)
                self.assertIsNone(usage_episodes.current(home))
        record(home, limit_body(T0 + 3600), T0)
        self.assertEqual(seconds(usage_episodes.current(home)['seen_at']), T0)

    def test_an_unwritable_home_never_raises(self):
        home = tmp_home(self)
        usage_episodes.path(home).mkdir()
        with mock.patch.object(usage_episodes, 'log_event') as log:
            record(home, limit_body(T0 + 3600), T0)
        self.assertIsNone(usage_episodes.current(home))
        self.assertEqual(log.call_args.args, ('usage_episode_failed',))


if __name__ == '__main__':
    unittest.main()
