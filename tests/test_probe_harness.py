"""Acceptance-harness verification against a scripted fake Codex binary.

The probe script drives the desktop app-server over stdio; CODEX_BIN swaps
in this fake so the harness legs themselves are proven offline: compact
failure fails verification, compact-then-switch retrieves the marker, media
is attached rather than silently dropped, and expected errors exit clean.
No network, no billing, no desktop app.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'tools' / 'probe_codex_runtime.py'
MARKER = 'CODEX_OPENROUTER_OK_719'

FAKE_BIN = '''#!/usr/bin/env python3
import json
import os
import sys
MARKER = 'CODEX_OPENROUTER_OK_719'
def send(obj):
    sys.stdout.write(json.dumps(obj) + '\\n')
    sys.stdout.flush()
def read():
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    return json.loads(line)
turns = 0
while True:
    msg = read()
    mid, method = msg.get('id'), msg.get('method')
    params = msg.get('params', {})
    if mid is not None and method is None:
        continue  # tool result delivery
    if method in (None, 'initialized'):
        continue
    if method == 'initialize':
        send({'id': mid, 'result': {'ok': True}})
    elif method == 'model/list':
        send({'id': mid, 'result': {'data': [{'model': 'fake-model'}]}})
    elif method == 'thread/start':
        rec = os.environ.get('FAKE_RECORD')
        if rec:
            open(rec, 'a').write('provider=' + str(params.get('modelProvider')) + '\\n')
        send({'id': mid, 'result': {'thread': {'id': 't1'},
                                    'modelProvider': 'openai', 'model': 'm'}})
    elif method == 'turn/start':
        send({'id': mid, 'result': {}})
        turns += 1
        blob = json.dumps(params.get('input'))
        if os.environ.get('FAKE_FIRST_ERROR') and turns == 1:
            send({'method': 'error',
                  'params': {'error': {'message': os.environ['FAKE_FIRST_ERROR']}}})
        elif 'solid color' in blob:
            send({'method': 'item/completed',
                  'params': {'item': {'type': 'agentMessage',
                                      'text': os.environ.get('FAKE_COLOR', 'red')}}})
            send({'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}})
        elif 'model' in params:
            rec = os.environ.get('FAKE_RECORD')
            if rec:
                open(rec, 'a').write(params['model'] + '\\n')
            send({'method': 'item/completed',
                  'params': {'item': {'type': 'agentMessage',
                                      'text': os.environ.get('FAKE_SWITCH_TEXT', MARKER)}}})
            send({'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}})
        else:
            rec = os.environ.get('FAKE_RECORD')
            if rec:
                open(rec, 'a').write(blob + '\\n')
            send({'method': 'item/tool/call', 'id': 'ev1',
                  'params': {'tool': 'echo_probe', 'arguments': {'value': 'probe'}}})
            read()  # tool result
            send({'method': 'item/completed',
                  'params': {'item': {'type': 'agentMessage', 'text': MARKER}}})
            send({'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}})
    elif method == 'thread/compact/start':
        send({'id': mid, 'result': {}})
        mode = os.environ.get('FAKE_COMPACT', 'ok')
        if mode == 'error':
            send({'method': 'error', 'params': {'error': {'message': 'compact boom'}}})
        else:
            ok = mode == 'ok'
            send({'method': 'turn/completed',
                  'params': {'turn': {'status': 'completed' if ok else 'failed',
                                      'error': None if ok else 'out of context'}}})
    else:
        send({'id': mid, 'result': {}})
'''


def _slug_with(test, capable):
    rows = json.loads((ROOT / 'codex_router' / 'models.json').read_text())
    for row in rows:
        if ('image' in row.get('modalities', [])) == capable:
            return row['slug']
    test.fail('no image-capable model in registry' if capable else 'no text-only model')


class ProbeHarnessTests(unittest.TestCase):
    def _fake_bin(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = Path(tmp) / 'fake-codex'
        path.write_text(FAKE_BIN)
        os.chmod(path, 0o755)
        return str(path)

    def _run(self, *args, **env):
        full = dict(os.environ, CODEX_BIN=self._fake_bin(), **env)
        return subprocess.run([sys.executable, str(PROBE), *args],
                              capture_output=True, text=True, timeout=60,
                              cwd=str(ROOT), env=full)

    def test_round_trip_passes(self):
        proc = self._run('fake-model')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"desktop_runtime_tool_round_trip": "passed"', proc.stdout)

    def test_provider_flag_reaches_thread_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = str(Path(tmp) / 'record.jsonl')
            proc = self._run('fake-model', '--provider', 'scg_router', FAKE_RECORD=rec)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            self.assertIn('"desktop_runtime_tool_round_trip": "passed"', proc.stdout)
            self.assertIn('provider=scg_router', Path(rec).read_text().splitlines())

    def test_compact_failure_fails_verification(self):
        proc = self._run('fake-model', '--compact', FAKE_COMPACT='fail')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('desktop_runtime_tool_round_trip": "passed"', proc.stdout)
        self.assertIn('Compaction failed', proc.stderr)

    def test_compact_error_fails_verification(self):
        proc = self._run('fake-model', '--compact', FAKE_COMPACT='error')
        self.assertNotEqual(proc.returncode, 0)

    def test_compact_twice_reports_both(self):
        proc = self._run('fake-model', '--compact', '--compact-twice')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertEqual(proc.stdout.count('"compaction_status": "completed"'), 2)

    def test_compact_then_switch_retrieves_marker(self):
        proc = self._run('fake-model', '--compact-then-switch')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"history_preserved": true', proc.stdout)

    def test_switch_to_custom_target(self):
        proc = self._run('fake-model', '--switch', '--switch-to', 'custom-model')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"switch_to": "custom-model"', proc.stdout)

    def test_lost_marker_fails_loudly(self):
        proc = self._run('fake-model', '--switch', FAKE_SWITCH_TEXT='something else')
        self.assertNotEqual(proc.returncode, 0)

    def test_expected_error_exits_clean(self):
        proc = self._run('fake-model', '--expect-error', 'reasoning effort',
                         FAKE_FIRST_ERROR='model does not support reasoning effort xhigh')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"expected_error_matched": true', proc.stdout)

    def test_unexpected_error_still_fails(self):
        proc = self._run('fake-model', '--expect-error', 'reasoning effort',
                         FAKE_FIRST_ERROR='upstream exploded')
        self.assertNotEqual(proc.returncode, 0)

    def test_image_evidence_for_capable_model(self):
        slug = _slug_with(self, True)
        with tempfile.TemporaryDirectory() as tmp:
            rec = str(Path(tmp) / 'record.jsonl')
            proc = self._run(slug, '--image', FAKE_RECORD=rec)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            self.assertIn('"media_color_seen": true', proc.stdout)
            recorded = Path(rec).read_text()
            self.assertIn('"type": "image"', recorded)
            self.assertIn('"url": "data:image/png;base64,', recorded)
            self.assertNotIn('image_url', recorded)

    def test_image_strip_path_for_text_only_model(self):
        slug = _slug_with(self, False)
        proc = self._run(slug, '--image')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"image_capable": false', proc.stdout)
        self.assertNotIn('media_color_seen', proc.stdout)

    def test_audio_attaches_and_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = str(Path(tmp) / 'record.jsonl')
            proc = self._run('fake-model', '--audio', FAKE_RECORD=rec)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            recorded = Path(rec).read_text()
            self.assertIn('"type": "audio"', recorded)
            self.assertIn('"url": "data:audio/wav;base64,', recorded)
            self.assertNotIn('audio_url', recorded)


if __name__ == '__main__':
    unittest.main()
