"""Offline checks for the direct OpenRouter shape probe.

Each shape's body keeps its marker in the half the model must read, the
default run prints only the contract verdict, and live mode sends exactly one
attempt per planned call inside its cap. The network is mocked throughout,
and neither the key nor any reply or request text reaches the output.
"""
import io
import json
import os
import unittest
import urllib.error
import urllib.response
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from ai_router import registry, wire_shape
from tests.harness import isolated_home
from tools import probe_wire_shapes as probe

KEY = 'sk-or-v1-test-key'
CONTENT = 'SYNTH-CONTENT-CANARY-wire-shapes-7d41'
MIMO, MUSE, DEEPSEEK = 'xiaomi/mimo-v2.6-flash', 'meta/muse-spark-1.3', 'deepseek/deepseek-v4.1-flash'
# shape: (input item types, declared tool types, the item type holding the marker)
EXPECTED = {
    'custom_declared': (['message', 'custom_tool_call', 'custom_tool_call_output'], ['custom'],
                        'custom_tool_call_output'),
    'custom_undeclared': (['message', 'custom_tool_call', 'custom_tool_call_output'], [],
                          'custom_tool_call_output'),
    'apply_patch': (['message', 'apply_patch_call', 'apply_patch_call_output'], [],
                    'apply_patch_call_output'),
    'tool_search': (['message', 'tool_search_call', 'tool_search_output'], ['tool_search'],
                    'tool_search_output'),
    'reasoning': (['message', 'reasoning', 'message', 'message'], [], 'message'),
}
LIVE_PLAN = ('--model', MIMO, '--model', MUSE, '--shape', 'custom_undeclared', '--shape', 'apply_patch')


def run(*argv):
    """(exit code, stdout) for one probe run."""
    out = io.StringIO()
    with redirect_stdout(out):
        try:
            code = probe.main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def reply(text, reasoning='', model=MIMO):
    """A 200 reply with endpoint metadata, a reasoning item and a message."""
    body = {'model': model,
            'openrouter_metadata': {'endpoints': {'available': [
                {'provider': 'Novita', 'selected': True}]}},
            'output': [{'type': 'reasoning',
                        'content': [{'type': 'reasoning_text', 'text': reasoning}]},
                       {'type': 'message', 'role': 'assistant',
                        'content': [{'type': 'output_text', 'text': text}]}]}
    return urllib.response.addinfourl(io.BytesIO(json.dumps(body).encode()), {},
                                      'https://synthetic', 200)


class ShapeBodyTests(unittest.TestCase):
    def test_each_shape_keeps_its_marker_in_the_half_the_model_must_read(self):
        entry = registry.by_slug(MIMO)
        for shape, (kinds, declared, holder) in EXPECTED.items():
            with self.subTest(shape=shape):
                body = probe.shape_body(shape, entry)
                self.assertEqual([item['type'] for item in body['input']], kinds)
                self.assertEqual([tool['type'] for tool in body['tools']], declared)
                self.assertEqual(wire_shape.pair_problems(body['input']), {})
                self.assertEqual(json.dumps(body).count(probe.MARKER), 1)
                holders = [item for item in body['input'] if probe.MARKER in json.dumps(item)]
                self.assertEqual(holders[0]['type'], holder)
                self.assertNotEqual(holders[0].get('role'), 'user')
                self.assertEqual((body['model'], body['reasoning'], body['max_output_tokens']),
                                 (MIMO, {'effort': 'low'}, probe.MAX_OUTPUT_TOKENS))

    def test_a_row_without_low_effort_keeps_its_own_default(self):
        body = probe.shape_body('apply_patch', registry.by_slug('anthropic/claude-haiku-4.5'))
        self.assertNotIn('reasoning', body)


class OfflineRunTests(unittest.TestCase):
    def test_default_run_prints_the_contract_verdict_and_sends_nothing(self):
        with mock.patch('urllib.request.urlopen') as urlopen:
            code, out = run('--model', MIMO, '--model', DEEPSEEK)
        urlopen.assert_not_called()
        self.assertEqual(code, 0)
        lines = {(line['row'], line['shape']): line for line in map(json.loads, out.splitlines())}
        self.assertEqual(len(lines), 2 * len(probe.SHAPES))
        self.assertNotIn(probe.MARKER, out)
        self.assertTrue(all(line['violations'] == {} for line in lines.values()))
        unverified = {'item.unverified_type': 2}
        self.assertEqual(lines[(MIMO, 'apply_patch')]['warnings'], unverified)
        self.assertEqual(lines[(MIMO, 'reasoning')]['warnings'], {})
        # DeepSeek alone took custom items as sent (17 Sep), never apply_patch ones.
        self.assertEqual(lines[(DEEPSEEK, 'custom_undeclared')]['warnings'], {})
        self.assertEqual(lines[(DEEPSEEK, 'apply_patch')]['warnings'], unverified)

    def test_only_openrouter_registry_rows_are_accepted(self):
        for slug in ('gpt-6-luna', 'synthetic/not-a-row'):
            with self.subTest(slug=slug):
                self.assertNotEqual(run('--model', slug)[0], 0)


class LiveRunTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(isolated_home(self))
        env = mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': KEY})
        env.start()
        self.addCleanup(env.stop)

    def test_live_needs_a_cap_that_covers_every_planned_call(self):
        with mock.patch('urllib.request.urlopen') as urlopen, \
                mock.patch.object(probe, 'live_target') as target:
            for cap in ((), ('--max-calls', '3'), ('--max-calls', '25')):
                with self.subTest(cap=cap):
                    code, out = run('--live', *LIVE_PLAN, *cap)
                    self.assertNotEqual(code, 0)
                    self.assertEqual(out, '')
        urlopen.assert_not_called()
        target.assert_not_called()  # a refused run never reads the key

    def test_a_malformed_region_is_refused_before_any_call(self):
        # The router refuses this state at startup; the probe must not fall
        # back to the global host for it.
        for region in (None, 7, ['eu'], 'mars'):
            with self.subTest(region=region), mock.patch('urllib.request.urlopen') as urlopen:
                (self.home / 'mixed-router-state.json').write_text(
                    json.dumps({'openrouter_region': region}))
                self.assertNotEqual(run('--live', '--max-calls', '4', *LIVE_PLAN)[0], 0)
                urlopen.assert_not_called()

    def test_each_call_is_one_attempt_and_prints_only_names_codes_and_flags(self):
        (self.home / 'mixed-router-state.json').write_text(json.dumps({'openrouter_region': 'eu'}))
        refusal = json.dumps({'error': {'code': 400, 'message': CONTENT, 'metadata': {
            'provider_name': 'DeepInfra', 'raw': CONTENT}}}).encode()
        answers = [reply('Answer: ' + probe.MARKER + ' ' + CONTENT),
                   urllib.error.HTTPError('https://synthetic', 400, 'Bad Request', {},
                                          io.BytesIO(refusal)),
                   urllib.error.URLError(CONTENT),
                   reply(CONTENT, reasoning=probe.MARKER, model='prose ' + CONTENT)]
        with mock.patch('urllib.request.urlopen', side_effect=answers) as urlopen:
            code, out = run('--live', '--max-calls', '4', *LIVE_PLAN)
        self.assertEqual(code, 1)
        self.assertEqual(urlopen.call_count, 4)
        lines = [json.loads(line) for line in out.splitlines()]
        self.assertEqual([(line['row'], line['shape'], line['status'], line['marker'])
                          for line in lines],
                         [(MIMO, 'custom_undeclared', 200, True), (MIMO, 'apply_patch', 400, False),
                          (MUSE, 'custom_undeclared', None, False), (MUSE, 'apply_patch', 200, False)])
        self.assertEqual([line['serving_endpoint'] for line in lines],
                         ['Novita', 'DeepInfra', None, 'Novita'])
        self.assertEqual([line['served_model'] for line in lines], [MIMO, None, None, None])
        self.assertEqual({key for line in lines for key in line},
                         {'shape', 'row', 'effort', 'status', 'served_model',
                          'serving_endpoint', 'marker'})
        for text in (KEY, CONTENT, probe.MARKER):
            self.assertNotIn(text, out)
        request = urlopen.call_args_list[0].args[0]
        self.assertEqual(request.full_url, 'https://eu.openrouter.ai/api/v1/responses')
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + KEY)
        self.assertEqual(request.get_header('X-openrouter-metadata'), 'enabled')
        self.assertEqual(json.loads(request.data)['input'][1]['type'], 'custom_tool_call')


if __name__ == '__main__':
    unittest.main()
