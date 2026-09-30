"""The loader proof, spoken over pipes to a fake Codex app server.

Only `switched` is ever proven: the config must load with no managed
provider and no account. An error reply, silence or a loader that cannot
start fails. The CLI comes from the app that was found, and the child gets
CODEX_HOME and none of the caller's OpenAI or Codex overrides.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests._platform import unix_only

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


proof = _load('codex_config_proof_test', 'packaging/codex_config_proof.py')
FAKE = '''#!%s
import json, os, sys
from pathlib import Path
Path(os.environ['FAKE_RECORD']).write_text(json.dumps(
    {k: v for k, v in os.environ.items() if k.startswith(('CODEX_', 'OPENAI_'))}))
plan = json.loads(os.environ['FAKE_PLAN'])
if plan.get('exit'):
    sys.exit(1)
for line in sys.stdin:
    message = json.loads(line)
    method, ident = message.get('method'), message.get('id')
    if ident is None:
        continue
    results = {'initialize': {'userAgent': 'fake'},
               'account/read': {'account': plan.get('account'), 'requiresOpenaiAuth': False},
               'configRequirements/read': {'requirements': plan.get('requirements')}}
    reply = ({'id': ident, 'error': {'code': -32600, 'message': 'no'}}
             if method in plan.get('errors', ()) else {'id': ident, 'result': results[method]})
    print(json.dumps({'method': 'notice', 'params': {}}), flush=True)
    print(json.dumps(reply), flush=True)
''' % sys.executable


@unix_only
class LoaderProofTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.loader = self.root / 'codex'
        self.loader.write_text(FAKE)
        self.loader.chmod(0o755)

    def prove(self, **plan):
        record = self.root / 'env.json'
        env = dict(os.environ, CODEX_BIN=str(self.loader), FAKE_RECORD=str(record),
                   FAKE_PLAN=json.dumps(plan), OPENAI_API_KEY='placeholder',
                   CODEX_SANDBOX='seatbelt')
        answer = proof.prove(None, codex_home=self.root / 'home', env=env, timeout=10)
        return answer, json.loads(record.read_text())

    def test_switched_answers(self):
        for plan, want in (
                ({}, True),
                ({'account': {'type': 'chatgpt'}}, False),
                ({'requirements': {'modelProvider': 'openai'}}, False),
                ({'requirements': {'allowedSandboxModes': ['read-only']}}, True)):
            with self.subTest(plan=plan):
                self.assertIs(self.prove(**plan)[0], want)

    def test_error_replies_and_a_loader_that_exits_or_cannot_start_fail(self):
        for plan in ({'errors': ['configRequirements/read']}, {'errors': ['account/read']},
                     {'errors': ['initialize']}, {'exit': True}):
            with self.subTest(plan=plan):
                self.assertIs(self.prove(**plan)[0], False)
        self.assertIs(proof.prove(None, env={'CODEX_BIN': str(self.root / 'missing')}), False)
        self.assertIs(proof.prove(self.root / 'Empty.app', env={}), False)

    def test_child_reads_only_codex_home(self):
        _, seen = self.prove()
        self.assertEqual(seen, {'CODEX_HOME': str(self.root / 'home')})

    def test_cli_comes_from_the_found_app_in_the_probe_tools_order(self):
        tools = _load('appserver_probe_order_test', 'tools/appserver_probe.py')
        self.assertEqual(tuple('/Applications/ChatGPT.app/' + rel for rel in proof.BUNDLED),
                         tools.BUNDLED_CODEX)
        app = self.root / 'Apps' / 'ChatGPT.app'  # found outside /Applications
        for rel in reversed(proof.BUNDLED):
            with self.subTest(rel=rel):
                (app / rel).parent.mkdir(parents=True, exist_ok=True)
                (app / rel).touch()
                self.assertEqual(proof.codex_bin({}, app), str(app / rel))
        self.assertEqual(proof.codex_bin({'CODEX_BIN': '/chosen/codex'}, app), '/chosen/codex')
        self.assertIsNone(proof.codex_bin({}, None))


if __name__ == '__main__':
    unittest.main()
