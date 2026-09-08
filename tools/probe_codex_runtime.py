import base64
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

try:
    from tools.probe_media import red_png, silent_wav
except ImportError:  # run as a script: the sibling module is on sys.path
    from probe_media import red_png, silent_wav

ROOT = Path(__file__).resolve().parent
CODEX_BIN = os.environ.get('CODEX_BIN', '/Applications/ChatGPT.app/Contents/Resources/codex')
cfg = {'model_provider': 'openai', 'model_reasoning_effort': 'low'}
if '--reasoning-summary' in sys.argv:
    # Plan 044 Step 3: ask the client for reasoning summaries on this thread.
    cfg['model_reasoning_summary'] = 'auto'
    if '--catalog' not in sys.argv:
        # Temporary catalogue flipping the target entry to auto summaries.
        # The leg requires default_reasoning_summary auto with parameter
        # support; built from the registry entry so other fields stay put.
        sys.path.insert(0, str(ROOT.parent))
        from codex_router import catalogue, registry
        if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
            _rs_model = registry.by_slug(sys.argv[1])
            _rs_entry = catalogue.openrouter_entry(_rs_model) if _rs_model else None
            if _rs_entry is not None:
                _rs_entry['default_reasoning_summary'] = 'auto'
                _rs_entry['supports_reasoning_summary_parameter'] = True
                _rs_path = Path(tempfile.mkdtemp(prefix='rs-catalog-')) / 'reasoning-summary-catalog.json'
                _rs_path.write_text(json.dumps({'models': [_rs_entry]}))
                cfg['model_catalog_json'] = str(_rs_path)
if '--apply-patch' in sys.argv:
    # Plan 044 Step 3: freeform apply_patch on a scratch dir. The temp
    # catalogue flips the target entry to freeform; the thread runs with
    # workspace-write sandbox rooted at a temp cwd holding note.txt.
    sys.path.insert(0, str(ROOT.parent))
    from codex_router import catalogue, registry
    _ap_dir = Path(tempfile.mkdtemp(prefix='ap-probe-'))
    (_ap_dir / 'note.txt').write_text('alpha\n')
    if '--catalog' not in sys.argv and len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
        _ap_model = registry.by_slug(sys.argv[1])
        _ap_entry = catalogue.openrouter_entry(_ap_model) if _ap_model else None
        if _ap_entry is not None:
            _ap_entry['apply_patch_tool_type'] = 'freeform'
            _ap_path = Path(tempfile.mkdtemp(prefix='ap-catalog-')) / 'apply-patch-catalog.json'
            _ap_path.write_text(json.dumps({'models': [_ap_entry]}))
            cfg['model_catalog_json'] = str(_ap_path)
if '--capture-tools' in sys.argv:
    cfg['openai_base_url'] = sys.argv[sys.argv.index('--capture-tools') + 1]
if '--catalog' in sys.argv:
    cfg['model_catalog_json'] = sys.argv[sys.argv.index('--catalog') + 1]
if '--router-state' in sys.argv:
    state = json.loads(Path(sys.argv[sys.argv.index('--router-state') + 1]).read_text())
    cfg['openai_base_url'] = f"http://127.0.0.1:{state['port']}/{state['token']}/backend-api/codex"
if '--provider' in sys.argv:
    # No-subscription acceptance: drive thread/start on a custom provider
    # (e.g. scg_router) instead of the default ChatGPT-subscription one.
    cfg['model_provider'] = sys.argv[sys.argv.index('--provider') + 1]
cfg.update(project_doc_max_bytes=0, developer_instructions='Synthetic protocol test only.',
           web_search='disabled', approval_policy='never',
           sandbox_mode='workspace-write' if '--apply-patch' in sys.argv else 'read-only')
cfg['features'] = {k: False for k in ['apps', 'shell_tool', 'collab', 'multi_agent', 'code_mode']}
if '--capture-tools' in sys.argv:
    cfg['features'] = {'memories': False}  # Capture native schemas; the local sink never calls a model.
args = [CODEX_BIN, 'app-server', '--stdio']

def flatten(d, prefix=''):
    for k, v in d.items():
        path = prefix + k
        if isinstance(v, dict):
            flatten(v, path + '.')
        else:
            args.extend(['-c', path + '=' + json.dumps(v)])

flatten(cfg)
args.extend(['-c', 'mcp_servers={}'])
p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, cwd=ROOT)
events = queue.Queue()
def drain_stderr():
    for _ in p.stderr:
        pass  # Drain diagnostics without logging potentially secret-bearing URLs.

threading.Thread(target=drain_stderr, daemon=True).start()

def read():
    for line in p.stdout:
        try:
            events.put(json.loads(line))
        except ValueError:
            pass
    events.put({'eof': True})

threading.Thread(target=read, daemon=True).start()
deadline = time.monotonic() + (180 if '--capture-tools' in sys.argv else 90)
seq = 0
calls = 0
marker = 'CODEX_OPENROUTER_OK_719'
trace = []

def send(value):
    p.stdin.write(json.dumps(value) + '\n')
    p.stdin.flush()

def next_event():
    event = events.get(timeout=max(0.01, deadline - time.monotonic()))
    if '--capture-tools' in sys.argv and event.get('method'):
        print(json.dumps({'runtime_event': event['method'], 'request': 'id' in event}), flush=True)
        if event['method'] == 'error':
            print(re.sub(r'https?://[^\s"<>]+', '[URL]', json.dumps(event.get('params')))[:1800], flush=True)
    if 'eof' in event:
        raise RuntimeError('App server exited')
    return event

def rpc(method, params):
    global seq
    seq += 1
    send({'id': seq, 'method': method, 'params': params})
    while True:
        event = next_event()
        if event.get('id') == seq and 'method' not in event:
            if 'error' in event:
                raise RuntimeError(str(event['error']))
            return event['result']

def _flag_value(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None

def switch_target():
    return _flag_value('--switch-to') or 'z-ai/glm-5.3-flash'

def model_modalities(model):
    try:
        rows = json.loads((ROOT.parent / 'codex_router' / 'models.json').read_text())
    except (OSError, ValueError):
        return []
    return next((row.get('modalities', []) for row in rows if row.get('slug') == model), [])

def media_items():
    """Attached synthetic media for --image/--audio; sizes are the evidence."""
    items = []
    if '--image' in sys.argv:
        items.append({'type': 'image',
                      'url': 'data:image/png;base64,' + base64.b64encode(red_png()).decode()})
    if '--audio' in sys.argv:
        # Audio key mirrors the verified image shape; still unproven live
        # (upstream rejects the leg with invalid_prompt).
        items.append({'type': 'audio',
                      'url': 'data:audio/wav;base64,' + base64.b64encode(silent_wav()).decode()})
    return items

def run_switch_leg(thread, target):
    rpc('turn/start', {'threadId': thread, 'model': target, 'effort': 'low',
        'input': [{'type': 'text', 'text': 'Without calling any tools, repeat the exact result returned by echo_probe in the previous turn.', 'text_elements': []}]})
    answer = ''
    while True:
        event = next_event()
        if event.get('method') == 'item/completed' and event['params']['item'].get('type') == 'agentMessage':
            answer = event['params']['item'].get('text', '')
        if event.get('method') == 'turn/completed':
            turn = event['params']['turn']
            assert turn['status'] == 'completed', str(turn.get('error'))
            assert marker in answer, 'Cross-provider history result: ' + repr(answer)
            print(json.dumps({'switch_to': target, 'history_preserved': True}), flush=True)
            break
        if event.get('method') == 'error':
            raise RuntimeError(str(event['params']))

def run_compact(thread):
    """Compact once; any failure raises so verification fails with it."""
    rpc('thread/compact/start', {'threadId': thread})
    while True:
        event = next_event()
        if event.get('method') == 'turn/completed':
            turn = event['params']['turn']
            if turn['status'] != 'completed':
                raise RuntimeError('Compaction failed: ' + str(turn.get('error')))
            print(json.dumps({'compaction_status': turn['status']}), flush=True)
            return
        if event.get('method') == 'error':
            raise RuntimeError('Compaction error: ' + str(event['params'].get('error')))


try:
    rpc('initialize', {'clientInfo': {'name': 'openrouter_probe', 'version': '1.0'},
                       'capabilities': {'experimentalApi': True}})
    send({'method': 'initialized', 'params': {}})
    models = rpc('model/list', {'includeHidden': False})
    print(json.dumps({'catalog': [m['model'] for m in models['data']]}), flush=True)
    model = sys.argv[1]
    input_schema = {'type': 'object', 'properties': {'value': {'type': 'string'}},
                    'required': ['value'], 'additionalProperties': False}
    if '--recursive' in sys.argv:
        input_schema['properties']['tree'] = {'$ref': '#/$defs/Node'}
        input_schema['$defs'] = {'Node': {'type': 'object', 'properties': {
            'name': {'type': 'string'}, 'children': {'type': 'array', 'items': {'$ref': '#/$defs/Node'}}}}}
    dynamic = {'type': 'function', 'name': 'echo_probe', 'deferLoading': '--deferred' in sys.argv,
               'description': 'Looks up and returns a synthetic test result for the supplied probe name.', 'inputSchema': input_schema}
    dynamic_tools = [{'type': 'namespace', 'name': 'probe', 'description': 'Synthetic lookup tools.', 'tools': [dynamic]}] if '--deferred' in sys.argv else [dynamic]
    if '--large-catalog' in sys.argv:
        assert '--deferred' in sys.argv
        dynamic_tools[0]['tools'].extend({'type': 'function', 'name': f'unrelated_{i}',
            'deferLoading': True, 'description': 'Unused synthetic tool.', 'inputSchema': {'type': 'object', 'properties': {}}}
            for i in range(500))
    t = rpc('thread/start', {'model': model, 'modelProvider': cfg['model_provider'], 'cwd': str(_ap_dir if '--apply-patch' in sys.argv else ROOT),
        'ephemeral': True, 'approvalPolicy': 'never',
        'sandbox': 'workspace-write' if '--apply-patch' in sys.argv else 'read-only',
        'baseInstructions': 'This is a synthetic protocol test. ' + ('Use tool_search to discover probe.echo_probe, then call it once. ' if '--deferred' in sys.argv else 'Only call echo_probe once. ') + 'Do not use unrelated tools or read any files.' + (' After this, you will be asked to edit note.txt with apply_patch.' if '--apply-patch' in sys.argv else ''),
        'developerInstructions': ('Discover probe.echo_probe using tool_search, then call the discovered function' if '--deferred' in sys.argv else 'Call echo_probe') + ' with the user supplied value, then return the tool result exactly.',
        'dynamicTools': dynamic_tools})
    thread = t['thread']['id']
    print(json.dumps({'runtime_provider': t.get('modelProvider'), 'runtime_model': t.get('model')}), flush=True)
    attached = media_items()
    rpc('turn/start', {'threadId': thread, 'input': attached + [{'type': 'text', 'text': ('First discover echo_probe with tool_search. ' if '--deferred' in sys.argv else '') + 'Call echo_probe with value "probe". Reply with its returned result only. You cannot know the result without calling the tool.',
                                                   'text_elements': []}], 'effort': _flag_value('--effort') or 'low'})
    answer = ''
    summary_seen = []
    while True:
        event = next_event()
        method = event.get('method', '')
        params = event.get('params', {})
        if method == 'item/tool/call':
            assert calls == 0 and params['tool'] == 'echo_probe', 'Unexpected tool or repeated call'
            assert params['arguments'] == {'value': 'probe'}, 'Unexpected arguments'
            calls += 1
            send({'id': event['id'], 'result': {'success': True,
                 'contentItems': [{'type': 'inputText', 'text': marker}]}})
        elif method == 'item/completed':
            item = params.get('item', {})
            trace.append(item.get('type'))
            if item.get('type') == 'agentMessage':
                answer = item.get('text', '')
            elif item.get('type') == 'reasoning' and '--reasoning-summary' in sys.argv:
                # Plan 044 Step 3: pass on non-empty streamed summary text.
                for entry in item.get('summary', []) or []:
                    if isinstance(entry, dict) and (entry.get('text') or '').strip():
                        summary_seen.append(entry['text'].strip()[:120])
                        break
            elif item.get('type') in ('commandExecution', 'fileChange', 'mcpToolCall', 'webSearch'):
                raise RuntimeError('Unexpected builtin tool')
        elif method == 'turn/completed':
            turn = params['turn']
            assert turn['status'] == 'completed', str(turn.get('error'))
            assert calls == 1 and answer.strip() == marker, f'Tool calls={calls}; synthetic final={answer[:1200]!r}'
            print(json.dumps({'model': model, 'desktop_runtime_tool_round_trip': 'passed', 'items': trace}), flush=True)
            if '--reasoning-summary' in sys.argv:
                print(json.dumps({'model': model, 'capability': 'reasoning_summary',
                                  'result': 'passed' if summary_seen else 'failed',
                                  'detail': 'summary text observed' if summary_seen else 'no reasoning summary streamed'}), flush=True)
            break
        elif method == 'error':
            print(re.sub(r'https?://[^\s"<>]+', '[URL]', json.dumps(params.get('error')))[:1600], flush=True)
            want = _flag_value('--expect-error')
            if want and want.lower() in json.dumps(params.get('error')).lower():
                print(json.dumps({'expected_error_matched': True}), flush=True)
                sys.exit(0)
            raise RuntimeError(str(params.get('error', {}).get('codexErrorInfo', 'Provider error')))
    if '--apply-patch' in sys.argv:
        rpc('turn/start', {'threadId': thread, 'effort': _flag_value('--effort') or 'low',
            'input': [{'type': 'text', 'text': 'Change alpha to beta in note.txt using apply_patch and stop.',
                       'text_elements': []}]})
        changes = 0
        while True:
            event = next_event()
            if event.get('method') == 'item/completed':
                if event['params']['item'].get('type') == 'fileChange':
                    changes += 1
            if event.get('method') == 'turn/completed':
                turn = event['params']['turn']
                assert turn['status'] == 'completed', str(turn.get('error'))
                try:
                    content = (_ap_dir / 'note.txt').read_text().strip()
                except OSError:
                    content = ''
                passed = changes == 1 and content == 'beta'
                print(json.dumps({'model': model, 'capability': 'apply_patch',
                                  'result': 'passed' if passed else 'failed',
                                  'detail': f'fileChange items={changes}; note.txt={content!r}'}), flush=True)
                break
            if event.get('method') == 'error':
                raise RuntimeError(str(event['params']))
    if attached:
        capable = 'image' in model_modalities(model)
        print(json.dumps({'media_attached': {'image_bytes': len(red_png()) if '--image' in sys.argv else 0,
                                             'audio_bytes': len(silent_wav()) if '--audio' in sys.argv else 0,
                                             'image_capable': capable}}), flush=True)
        if '--image' in sys.argv and capable:
            rpc('turn/start', {'threadId': thread, 'effort': 'low',
                'input': [{'type': 'text', 'text': 'What solid color is the image attached earlier? Reply with the color only.', 'text_elements': []}]})
            answer = ''
            while True:
                event = next_event()
                if event.get('method') == 'item/completed' and event['params']['item'].get('type') == 'agentMessage':
                    answer = event['params']['item'].get('text', '')
                if event.get('method') == 'turn/completed':
                    turn = event['params']['turn']
                    assert turn['status'] == 'completed', str(turn.get('error'))
                    assert 'red' in answer.lower(), 'Media evidence lost: ' + repr(answer)
                    print(json.dumps({'media_color_seen': True}), flush=True)
                    break
                if event.get('method') == 'error':
                    raise RuntimeError(str(event['params']))
    compact_then_switch = '--compact-then-switch' in sys.argv
    if '--switch' in sys.argv and not compact_then_switch:
        run_switch_leg(thread, switch_target())
    if '--compact' in sys.argv or compact_then_switch:
        run_compact(thread)
        if '--compact-twice' in sys.argv:
            run_compact(thread)
    if compact_then_switch:
        run_switch_leg(thread, switch_target())
finally:
    p.terminate()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
