"""Prepare-level and optional live proof for standalone delegation delivery.

Offline default runs the prepare-level assertion against the local source:
a captured no-call_id app-injected item must reach the OpenRouter prepared
body as a matched call+output pair carrying the marker. Prints PASS/FAIL.

--live forwards the same shape through the installed router to OpenRouter
(model deepseek/deepseek-v4.1-flash) and asserts the reply carries a
synthetic marker. Requires --max-calls N (1-24) as the paid-run gate and
    sends exactly one request and asserts both synthetic markers. Never
    prints ports, tokens, keys or content.
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
OPAQUE_MARKER = 'SYNTH_OPAQUE_REPLY_MARKER_719'
CIPHER_MARKER = 'SYNTH_WITHHELD_CIPHER_719'
LIVE_PROMPT = ('Reply with the two synthetic markers contained in the delivered '
               'tool results, separated by a space.')
STATE_PATH = Path.home() / '.codex/mixed-model-router/mixed-router-state.json'


def captured_item():
    return {'type': 'function_call_output', 'name': 'create_thread',
            'namespace': 'codex_app',
            'output': '<codex_delegation>' + MARKER + '</codex_delegation>'}


def captured_agent_message():
    return {'type': 'agent_message', 'author': '/root/probe_child', 'recipient': '/root',
            'content': [{'type': 'input_text', 'text': OPAQUE_MARKER},
                        {'type': 'encrypted_content', 'encrypted_content': CIPHER_MARKER}]}


class _OfflineKey:
    def key_for(self, provider_id=None):
        return 'offline-probe-key'


def prepare_offline():
    provider = providers.select(MODEL, '/responses', [])
    assert type(provider).__name__ == 'ExternalResponsesProvider', 'wrong provider'
    prepared = provider.prepare(
        MODEL, '/responses',
        {'model': MODEL, 'input': [captured_item(), captured_agent_message()]},
        b'raw', {}, _OfflineKey())
    data = json.loads(prepared.body)['input']
    assert len(data) == 4, 'standalone item dropped'
    for call, result in (data[:2], data[2:]):
        assert call.get('type') == 'function_call', 'no synthesized call'
        assert result.get('type') == 'function_call_output', 'no output'
        assert call.get('call_id') == result.get('call_id'), 'unmatched pair'
    assert MARKER in data[1].get('output', ''), 'delegation marker missing'
    recovered = data[3].get('output', '')
    assert OPAQUE_MARKER in recovered, 'readable reply marker missing'
    assert CIPHER_MARKER not in json.dumps(data), 'ciphertext leaked'
    assert MARKER not in LIVE_PROMPT and OPAQUE_MARKER not in LIVE_PROMPT


def run_live():
    state = json.loads(STATE_PATH.read_text())
    url = ('http://127.0.0.1:' + str(state['port']) + '/' + state['token']
           + '/backend-api/codex/responses')
    body = {'model': MODEL, 'input': [
        {'type': 'message', 'role': 'user', 'content': LIVE_PROMPT},
        captured_item(), captured_agent_message()]}
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read())
    text = ' '.join(block.get('text', '') for item in result.get('output', [])
                    for block in (item.get('content') or [])
                    if isinstance(block, dict))
    assert MARKER in text, 'delegation marker missing from reply'
    assert OPAQUE_MARKER in text, 'opaque-reply marker missing from reply'


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
