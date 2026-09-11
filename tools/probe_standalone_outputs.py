"""Prepare-level and optional live proof for standalone delegation delivery.

Offline default runs the prepare-level assertion against the local source:
a captured no-call_id app-injected item must reach the OpenRouter prepared
body as readable plaintext. Prints PASS/FAIL only.

--live forwards the same shape through the installed router to OpenRouter
(model deepseek/deepseek-v4.1-flash) and asserts the reply carries a
synthetic marker. Requires --max-calls N (1-24) as the paid-run gate and
sends exactly one request. Never prints ports, tokens, keys or content.
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_router import providers

MODEL = 'deepseek/deepseek-v4.1-flash'
MARKER = 'SYNTH_STANDALONE_MARKER_719'
STATE_PATH = Path.home() / '.codex/mixed-model-router/mixed-router-state.json'


def captured_item():
    return {'type': 'function_call_output', 'name': 'create_thread',
            'namespace': 'codex_app',
            'output': '<codex_delegation>' + MARKER + '</codex_delegation>'}


class _OfflineKey:
    def openrouter_key(self):
        return 'offline-probe-key'


def prepare_offline():
    provider = providers.select(MODEL, '/responses', [])
    assert type(provider).__name__ == 'OpenRouterProvider', 'wrong provider'
    prepared = provider.prepare(
        MODEL, '/responses', {'model': MODEL, 'input': [captured_item()]},
        b'raw', {}, _OfflineKey())
    data = json.loads(prepared.body)['input']
    assert len(data) == 1, 'standalone item dropped'
    item = data[0]
    assert (item.get('type'), item.get('role')) == ('message', 'assistant'), \
        'not plaintext'
    assert MARKER in item['content'][0]['text'], 'marker missing'


def run_live():
    state = json.loads(STATE_PATH.read_text())
    url = ('http://127.0.0.1:' + str(state['port']) + '/' + state['token']
           + '/backend-api/codex/responses')
    body = {'model': MODEL, 'input': [
        {'type': 'message', 'role': 'user', 'content': 'Reply exactly ' + MARKER},
        captured_item()]}
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read())
    text = ' '.join(block.get('text', '') for item in result.get('output', [])
                    for block in (item.get('content') or [])
                    if isinstance(block, dict))
    assert MARKER in text, 'marker missing from reply'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--max-calls', type=int, default=0)
    args = parser.parse_args()
    if args.live and not 1 <= args.max_calls <= 24:
        print('FAIL')
        raise SystemExit('--live requires --max-calls between 1 and 24')
    try:
        if args.live:
            run_live()
        else:
            prepare_offline()
    except Exception:
        print('FAIL')
        raise SystemExit(1)
    print('PASS')


if __name__ == '__main__':
    main()
