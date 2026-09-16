import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from tools.probe_media import red_png, silent_wav
except ImportError:  # run as a script: the sibling module is on sys.path
    from probe_media import red_png, silent_wav

try:
    from tools.appserver_probe import AppServer, scrub_env, AGENT_HANDOFFS
except ImportError:  # run as a script: the sibling module is on sys.path
    from appserver_probe import AppServer, scrub_env, AGENT_HANDOFFS

ROOT = Path(__file__).resolve().parent
CODEX_BIN = os.environ.get('CODEX_BIN', '/Applications/ChatGPT.app/Contents/Resources/codex')

def _flag_value(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


def _effective_home():
    home = os.environ.get('CODEX_HOME')
    if home:
        return home
    return os.path.join(os.path.expanduser('~'), '.codex')


def _home_routes_to_router(home):
    """True when the home's config points the client at a local router."""
    try:
        config = Path(home, 'config.toml').read_text()
    except OSError:
        return False
    return 'openrouter' in config.lower() or 'scg_router' in config.lower()


_codex_home = _flag_value('--codex-home')
_reaches_router = ('--router-state' in sys.argv or '--provider' in sys.argv
                   or '--capture-tools' in sys.argv)
if '--live-home' in sys.argv and (_codex_home or _reaches_router):
    print('refusing: --live-home is subscription-path only; it combines '
          'with neither --codex-home nor router flags', file=sys.stderr)
    raise SystemExit(2)
if _codex_home:
    live = os.path.realpath(_effective_home())
    given = os.path.realpath(_codex_home)
    if given == live or not os.path.relpath(given, live).startswith('..'):
        print('refusing: --codex-home must not be the live Codex home',
              file=sys.stderr)
        raise SystemExit(2)
if _reaches_router and not _codex_home:
    print('refusing: a leg that reaches a router needs --codex-home <dir> '
          'so the probe never touches the live Codex home', file=sys.stderr)
    raise SystemExit(2)
if (not _codex_home and '--live-home' not in sys.argv
        and '--help' not in sys.argv and '-h' not in sys.argv
        and _home_routes_to_router(_effective_home())):
    print('refusing: this Codex home routes to a local router; pass '
          '--codex-home <fresh dir>, or --live-home for an explicit '
          'subscription-path leg', file=sys.stderr)
    raise SystemExit(2)
_child_env = (scrub_env(os.environ, AGENT_HANDOFFS, inject={'CODEX_HOME': _codex_home})
              if _codex_home else dict(os.environ))


def print_usage():
    print('usage: probe_codex_runtime.py <slug> [--effort L] [--router-state F] '
          '[--catalog F] [--provider P] [--codex-home DIR] [--parallel] '
          '[--switch --switch-to S [--switch-back]] [--switch-in S] [--compact] '
          '[--image] [--web-search] [--experimental-tools] [--apply-patch] '
          '[--reasoning-summary] [--capture-tools URL]',
          file=sys.stderr)
    print('  --codex-home DIR: required for any leg reaching a router; the child '
          'app-server runs with a scrubbed env and CODEX_HOME=DIR.',
          file=sys.stderr)
    print('  --live-home: explicit opt-in to run on the ambient Codex home '
          '(subscription-path legs only; never with router flags).',
          file=sys.stderr)
    print('  --parallel: second thread asks for echo_probe and timing_probe in '
          'one step; pass when both calls arrive and both are answered.',
          file=sys.stderr)
    print('  --switch --switch-to S: switch out to S and back; --switch-in S: '
          'start on the argv slug, switch into S.',
          file=sys.stderr)


if '--help' in sys.argv or '-h' in sys.argv:
    print_usage()
    raise SystemExit(0)
cfg = {'model_provider': 'openai', 'model_reasoning_effort': 'low'}
if '--reasoning-summary' in sys.argv:
    # Plan 118 Step 3: ask the client for reasoning summaries on this thread.
    cfg['model_reasoning_summary'] = 'auto'
    if '--catalog' not in sys.argv:
        # Temporary catalogue flipping the target entry to auto summaries.
        # The leg requires default_reasoning_summary auto with parameter
        # support; built from the registry entry so other fields stay put.
        sys.path.insert(0, str(ROOT.parent))
        from ai_router import catalogue, registry
        if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
            _rs_model = registry.by_slug(sys.argv[1])
            _rs_entry = catalogue.external_entry(_rs_model) if _rs_model else None
            if _rs_entry is not None:
                _rs_entry['default_reasoning_summary'] = 'auto'
                _rs_entry['supports_reasoning_summary_parameter'] = True
                _rs_path = Path(tempfile.mkdtemp(prefix='rs-catalog-')) / 'reasoning-summary-catalog.json'
                _rs_path.write_text(json.dumps({'models': [_rs_entry]}))
                cfg['model_catalog_json'] = str(_rs_path)
if '--apply-patch' in sys.argv:
    # Plan 118 Step 3: freeform apply_patch on a scratch dir. The temp
    # catalogue flips the target entry to freeform; the thread runs with
    # workspace-write sandbox rooted at a temp cwd holding note.txt.
    sys.path.insert(0, str(ROOT.parent))
    from ai_router import catalogue, registry
    _ap_dir = Path(tempfile.mkdtemp(prefix='ap-probe-'))
    (_ap_dir / 'note.txt').write_text('alpha\n')
    if '--catalog' not in sys.argv and len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
        _ap_model = registry.by_slug(sys.argv[1])
        _ap_entry = catalogue.external_entry(_ap_model) if _ap_model else None
        if _ap_entry is not None:
            _ap_entry['apply_patch_tool_type'] = 'freeform'
            _ap_path = Path(tempfile.mkdtemp(prefix='ap-catalog-')) / 'apply-patch-catalog.json'
            _ap_path.write_text(json.dumps({'models': [_ap_entry]}))
            cfg['model_catalog_json'] = str(_ap_path)
if '--experimental-tools' in sys.argv and '--catalog' not in sys.argv:
    # Plan 118 Step 3: temporary catalogue advertising the clock tool.
    # Built from the registry entry so other fields stay put.
    sys.path.insert(0, str(ROOT.parent))
    from ai_router import catalogue, registry
    if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
        _xt_model = registry.by_slug(sys.argv[1])
        _xt_entry = catalogue.external_entry(_xt_model) if _xt_model else None
        if _xt_entry is not None:
            _xt_entry['experimental_supported_tools'] = ['clock']
            _xt_path = Path(tempfile.mkdtemp(prefix='xt-catalog-')) / 'exp-tools-catalog.json'
            _xt_path.write_text(json.dumps({'models': [_xt_entry]}))
            cfg['model_catalog_json'] = str(_xt_path)
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
           web_search='enabled' if '--web-search' in sys.argv else 'disabled',
           approval_policy='never',
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
deadline = time.monotonic() + (180 if '--capture-tools' in sys.argv else 90)
calls = 0
marker = 'CODEX_OPENROUTER_OK_719'
trace = []


def on_event(event):
    # --capture-tools prints runtime events; the shared class stays silent.
    if '--capture-tools' in sys.argv and event.get('method'):
        print(json.dumps({'runtime_event': event['method'], 'request': 'id' in event}), flush=True)
        if event['method'] == 'error':
            print(re.sub(r'https?://[^\s"<>]+', '[URL]', json.dumps(event.get('params')))[:1800], flush=True)


# Piped stderr drained silently, plain terminate: the shared AppServer
# default. Per-call timeout keeps the global-deadline wait shape.
server = AppServer(args, cwd=ROOT, env=_child_env, stderr=subprocess.PIPE,
                    on_event=on_event)


def send(value):
    server.send(value)


def next_event():
    return server.next_event(deadline=deadline)


def rpc(method, params):
    return server.rpc(method, params,
                      timeout=max(0.01, deadline - time.monotonic()))

def switch_target():
    return _flag_value('--switch-to') or 'z-ai/glm-5.3-flash'


def model_modalities(model):
    try:
        rows = json.loads((ROOT.parent / 'ai_router' / 'models.json').read_text())
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
    rpc('turn/start', {'threadId': thread, 'model': target, 'effort': _flag_value('--effort') or 'low',
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
    if '--union-root' in sys.argv:
        # xAI rejects non-object parameter roots; the router must string-wrap
        # this union the same way it wraps Meta's recursive schemas.
        input_schema = {'anyOf': [dict(input_schema), {'type': 'string'}]}
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
                # Plan 118 Step 3: pass on non-empty streamed summary text.
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
    if '--parallel' in sys.argv:
        # Plan 175 Step 1: open a second thread with timing_probe alongside
        # echo_probe and ask for both calls at once.
        second = {'type': 'function', 'name': 'timing_probe',
                  'description': 'Returns a synthetic timing marker.',
                  'inputSchema': {'type': 'object', 'properties': {}}}
        t2 = rpc('thread/start', {'model': model, 'modelProvider': cfg['model_provider'],
            'cwd': str(ROOT), 'ephemeral': True, 'approvalPolicy': 'never',
            'sandbox': 'read-only',
            'baseInstructions': 'This is a synthetic protocol test. Call echo_probe and timing_probe now, in parallel. Do not read any files.',
            'developerInstructions': 'Call echo_probe with the user supplied value and timing_probe, both now, in parallel, then return both results.',
            'dynamicTools': [dynamic, second]})
        p_thread = t2['thread']['id']
        rpc('turn/start', {'threadId': p_thread,
            'input': [{'type': 'text', 'text': 'Call echo_probe with value "probe" and timing_probe now, in parallel. Reply with both results.',
                       'text_elements': []}], 'effort': _flag_value('--effort') or 'low'})
        parallel_calls = {}
        stepped = False
        while True:
            event = next_event()
            if event.get('method') == 'item/tool/call':
                tool = event['params']['tool']
                assert tool in ('echo_probe', 'timing_probe'), 'Unexpected tool ' + str(tool)
                # One step means no completed item lands between the calls;
                # completions before the first call (userMessage, reasoning)
                # are the normal live ordering, not separate steps.
                assert not stepped, 'Parallel calls arrived in separate steps'
                args = event['params']['arguments']
                parallel_calls[tool] = args
                if tool == 'echo_probe':
                    assert args == {'value': 'probe'}, 'Unexpected arguments'
                    send({'id': event['id'], 'result': {'success': True,
                         'contentItems': [{'type': 'inputText', 'text': marker}]}})
                else:
                    send({'id': event['id'], 'result': {'success': True,
                         'contentItems': [{'type': 'inputText', 'text': 'tick-482'}]}})
            if event.get('method') == 'item/completed' and parallel_calls:
                stepped = True
            if event.get('method') == 'turn/completed':
                turn = event['params']['turn']
                assert turn['status'] == 'completed', str(turn.get('error'))
                assert set(parallel_calls) == {'echo_probe', 'timing_probe'}, \
                    'Parallel calls missing: saw=%s' % ','.join(sorted(parallel_calls))
                print(json.dumps({'model': model, 'capability': 'parallel',
                                  'result': 'passed',
                                  'detail': 'both calls in one step'}), flush=True)
                break
            if event.get('method') == 'error':
                raise RuntimeError(str(event['params']))
    if '--experimental-tools' in sys.argv:
        # Plan 118 Step 3: pass when a tool item named clock completes.
        rpc('turn/start', {'threadId': thread, 'effort': _flag_value('--effort') or 'low',
            'input': [{'type': 'text', 'text': 'Use the clock tool and reply with the hour only.',
                       'text_elements': []}]})
        clocked = False
        seen = []
        while True:
            event = next_event()
            if event.get('method') == 'item/completed':
                item = event['params']['item']
                seen.append(item.get('type'))
                # Pass on a completed item naming the clock tool. The saw=
                # diagnostic below records live item types; widen only on evidence.
                if item.get('tool') == 'clock':
                    clocked = True
            if event.get('method') == 'turn/completed':
                turn = event['params']['turn']
                assert turn['status'] == 'completed', str(turn.get('error'))
                print(json.dumps({'model': model, 'capability': 'experimental_tools',
                                  'result': 'passed' if clocked else 'failed',
                                  'detail': 'clock tool completed' if clocked else
                                  'no clock tool item; saw=%s' % ','.join(sorted(set(map(str, seen))))}), flush=True)
                break
            if event.get('method') == 'error':
                raise RuntimeError(str(event['params']))
    if '--web-search' in sys.argv:
        # Plan 118 Step 3: pass when a webSearch item completes and the turn
        # completes. The date itself is never asserted.
        rpc('turn/start', {'threadId': thread, 'effort': _flag_value('--effort') or 'low',
            'input': [{'type': 'text', 'text': "What is today's date according to a web search? Reply with the date only.",
                       'text_elements': []}]})
        searched = False
        while True:
            event = next_event()
            if event.get('method') == 'item/completed':
                if event['params']['item'].get('type') == 'webSearch':
                    searched = True
            if event.get('method') == 'turn/completed':
                turn = event['params']['turn']
                assert turn['status'] == 'completed', str(turn.get('error'))
                print(json.dumps({'model': model, 'capability': 'web_search',
                                  'result': 'passed' if searched else 'failed',
                                  'detail': 'webSearch item completed' if searched else 'no webSearch item'}), flush=True)
                break
            if event.get('method') == 'error':
                raise RuntimeError(str(event['params']))
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
            rpc('turn/start', {'threadId': thread, 'effort': _flag_value('--effort') or 'low',
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
    if '--switch-in' in sys.argv:
        # Plan 175 Step 1: the base turn above ran on the from-slug, so
        # switching into the target row exercises foreign history in and
        # native history out. Documented beside --switch/--switch-to.
        target = _flag_value('--switch-in')
        assert target, '--switch-in needs a target slug'
        run_switch_leg(thread, target)
    compact_then_switch = '--compact-then-switch' in sys.argv
    if '--switch' in sys.argv and not compact_then_switch:
        run_switch_leg(thread, switch_target())
        if '--switch-back' in sys.argv:
            run_switch_leg(thread, model)
    if '--compact' in sys.argv or compact_then_switch:
        run_compact(thread)
        if '--compact-twice' in sys.argv:
            run_compact(thread)
    if compact_then_switch:
        run_switch_leg(thread, switch_target())
finally:
    server.close()
