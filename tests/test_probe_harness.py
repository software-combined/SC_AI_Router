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
_ap_cwd = ''
if os.environ.get('FAKE_RECORD'):
    open(os.environ['FAKE_RECORD'], 'a').write('argv=' + json.dumps(sys.argv) + '\\n')
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
            open(rec, 'a').write('sandbox=' + str(params.get('sandbox')) + '\\n')
            open(rec, 'a').write('cwd=' + str(params.get('cwd')) + '\\n')
        _ap_cwd = params.get('cwd', '')
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
        elif 'clock tool' in blob and os.environ.get('FAKE_EXP_TOOLS'):
            if os.environ['FAKE_EXP_TOOLS'] == 'clocked':
                send({'method': 'item/completed',
                      'params': {'item': {'type': 'mcpToolCall', 'tool': 'clock'}}})
            send({'method': 'item/completed',
                  'params': {'item': {'type': 'agentMessage', 'text': 'seven'}}})
            send({'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}})
        elif 'web search' in blob and os.environ.get('FAKE_WEB_SEARCH'):
            if os.environ['FAKE_WEB_SEARCH'] == 'searched':
                send({'method': 'item/completed',
                      'params': {'item': {'type': 'webSearch'}}})
            send({'method': 'item/completed',
                  'params': {'item': {'type': 'agentMessage', 'text': 'synthetic-search-answer-482'}}})
            send({'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}})
        elif 'apply_patch' in blob and os.environ.get('FAKE_APPLY_PATCH'):
            mode = os.environ['FAKE_APPLY_PATCH']
            if mode in ('applied', 'deleted'):
                send({'method': 'item/completed',
                      'params': {'item': {'type': 'fileChange'}}})
                target = os.path.join(_ap_cwd, 'note.txt')
                if mode == 'applied':
                    open(target, 'w').write('beta\\n')
                else:
                    os.remove(target)
            send({'method': 'item/completed',
                  'params': {'item': {'type': 'agentMessage', 'text': 'done'}}})
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
            if os.environ.get('FAKE_REASONING_SUMMARY') == 'summary':
                send({'method': 'item/completed',
                      'params': {'item': {'type': 'reasoning',
                                          'summary': [{'type': 'summary_text',
                                                       'text': 'synthetic summary'}]}}})
            elif os.environ.get('FAKE_REASONING_SUMMARY') == 'empty':
                send({'method': 'item/completed',
                      'params': {'item': {'type': 'reasoning', 'summary': []}}})
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

    def _catalog_entry(self, flags):
        """Parse the temp catalog from -c flags; return its first entry."""
        catalog = next(f.split('=', 1)[1] for f in flags
                       if f.startswith('model_catalog_json='))
        return json.loads(Path(json.loads(catalog)).read_text())['models'][0]

    def _run_recorded(self, *args, **env):
        """Run the probe with FAKE_RECORD; return (proc, -c flags, record lines)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rec = str(Path(tmp.name) / 'record.jsonl')
        proc = self._run(*args, FAKE_RECORD=rec, **env)
        recorded = Path(rec).read_text().splitlines()
        argv = json.loads(next(l for l in recorded if l.startswith('argv='))[5:])
        return proc, [a for i, a in enumerate(argv) if argv[i - 1] == '-c'], recorded

    def test_round_trip_passes(self):
        proc = self._run('fake-model')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"desktop_runtime_tool_round_trip": "passed"', proc.stdout)

    def test_provider_flag_reaches_thread_start(self):
        proc, _, recorded = self._run_recorded('fake-model', '--provider', 'scg_router')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"desktop_runtime_tool_round_trip": "passed"', proc.stdout)
        self.assertIn('provider=scg_router', recorded)

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
        proc, _, recorded = self._run_recorded(slug, '--image')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"media_color_seen": true', proc.stdout)
        blob = '\n'.join(recorded)
        self.assertIn('"type": "image"', blob)
        self.assertIn('"url": "data:image/png;base64,', blob)
        self.assertNotIn('image_url', blob)

    def test_image_strip_path_for_text_only_model(self):
        slug = _slug_with(self, False)
        proc = self._run(slug, '--image')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"image_capable": false', proc.stdout)
        self.assertNotIn('media_color_seen', proc.stdout)

    def test_reasoning_summary_passes_on_summary_text(self):
        proc, flags, _ = self._run_recorded('z-ai/glm-5.3-flash', '--reasoning-summary',
                                            FAKE_REASONING_SUMMARY='summary')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"capability": "reasoning_summary"', proc.stdout)
        self.assertIn('"result": "passed"', proc.stdout)
        # Streamed summary content itself never reaches stdout.
        self.assertNotIn('synthetic summary', proc.stdout)
        # The leg's core contract: auto summary + temp catalog reach -c flags.
        auto = [f for f in flags if f.startswith('model_reasoning_summary=')]
        self.assertEqual(len(auto), 1, flags)
        self.assertIn('auto', auto[0])
        entry = self._catalog_entry(flags)
        self.assertEqual(entry['slug'], 'z-ai/glm-5.3-flash')
        self.assertEqual(entry['default_reasoning_summary'], 'auto')
        self.assertTrue(entry['supports_reasoning_summary_parameter'])

    def test_reasoning_summary_fails_without_summary_text(self):
        proc = self._run('z-ai/glm-5.3-flash', '--reasoning-summary',
                         FAKE_REASONING_SUMMARY='empty')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"capability": "reasoning_summary"', proc.stdout)
        self.assertIn('"result": "failed"', proc.stdout)

    def test_apply_patch_passes_on_file_change(self):
        proc, flags, recorded = self._run_recorded('z-ai/glm-5.3-flash', '--apply-patch',
                                                   FAKE_APPLY_PATCH='applied')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"capability": "apply_patch"', proc.stdout)
        self.assertIn('"result": "passed"', proc.stdout)
        # The leg's core contract: workspace-write + freeform catalog reach -c flags.
        self.assertEqual([f for f in flags if f.startswith('sandbox_mode=')],
                         ['sandbox_mode="workspace-write"'], flags)
        entry = self._catalog_entry(flags)
        self.assertEqual(entry['slug'], 'z-ai/glm-5.3-flash')
        self.assertEqual(entry['apply_patch_tool_type'], 'freeform')
        # The thread runs workspace-write rooted at the scratch dir.
        self.assertIn('sandbox=workspace-write', recorded)
        cwd = next(l[4:] for l in recorded if l.startswith('cwd='))
        self.assertTrue(Path(cwd, 'note.txt').exists(), recorded)

    def test_apply_patch_fails_without_file_change(self):
        proc = self._run('z-ai/glm-5.3-flash', '--apply-patch', FAKE_APPLY_PATCH='skipped')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"capability": "apply_patch"', proc.stdout)
        self.assertIn('"result": "failed"', proc.stdout)

    def test_apply_patch_fails_cleanly_when_file_deleted(self):
        proc = self._run('z-ai/glm-5.3-flash', '--apply-patch', FAKE_APPLY_PATCH='deleted')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"capability": "apply_patch"', proc.stdout)
        self.assertIn('"result": "failed"', proc.stdout)

    def test_web_search_passes_on_search_item(self):
        proc, flags, _ = self._run_recorded('z-ai/glm-5.3-flash', '--web-search',
                                            FAKE_WEB_SEARCH='searched')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"capability": "web_search"', proc.stdout)
        self.assertIn('"result": "passed"', proc.stdout)
        # Search answer content itself never reaches stdout.
        self.assertNotIn('synthetic-search-answer-482', proc.stdout)
        # The leg's core contract: the web_search feature reaches -c flags as enabled.
        self.assertEqual([f for f in flags if f.startswith('web_search=')],
                         ['web_search="enabled"'], flags)

    def test_web_search_fails_without_search_item(self):
        proc = self._run('z-ai/glm-5.3-flash', '--web-search', FAKE_WEB_SEARCH='skipped')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"capability": "web_search"', proc.stdout)
        self.assertIn('"result": "failed"', proc.stdout)

    def test_experimental_tools_passes_on_clock_item(self):
        proc, flags, _ = self._run_recorded('z-ai/glm-5.3-flash', '--experimental-tools',
                                            FAKE_EXP_TOOLS='clocked')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"capability": "experimental_tools"', proc.stdout)
        self.assertIn('"result": "passed"', proc.stdout)
        # Answer content itself never reaches stdout.
        self.assertNotIn('seven', proc.stdout)
        # The leg's core contract: the temp catalog advertises the clock tool.
        entry = self._catalog_entry(flags)
        self.assertEqual(entry['slug'], 'z-ai/glm-5.3-flash')
        self.assertEqual(entry['experimental_supported_tools'], ['clock'])

    def test_experimental_tools_fails_without_clock_item(self):
        proc = self._run('z-ai/glm-5.3-flash', '--experimental-tools', FAKE_EXP_TOOLS='skipped')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn('"capability": "experimental_tools"', proc.stdout)
        self.assertIn('"result": "failed"', proc.stdout)

    def test_audio_attaches_and_completes(self):
        proc, _, recorded = self._run_recorded('fake-model', '--audio')
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        blob = '\n'.join(recorded)
        self.assertIn('"type": "audio"', blob)
        self.assertIn('"url": "data:audio/wav;base64,', blob)
        self.assertNotIn('audio_url', blob)


if __name__ == '__main__':
    unittest.main()
