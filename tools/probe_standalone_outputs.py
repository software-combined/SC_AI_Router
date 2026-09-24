"""Prepare-level and optional live proof for delivered tool history.

Offline default prepares one --shape against the local source (--model,
default deepseek/deepseek-v4.1-flash) and asserts the OpenRouter body:
- standalone (default): a captured no-call_id app-injected item must arrive
  as a matched call+output pair carrying the marker;
- custom_pair: an undeclared custom tool call and its output, with no tools
  declared;
- apply_patch_pair: a completed apply_patch update_file call and its output.
Each replayed pair must keep its original types and shared call_id, and the
marker in its output. Prints PASS/FAIL and the model.

--live forwards the same shape through the installed router to OpenRouter
and asserts HTTP 200 and the synthetic markers in the reply. Requires
--max-calls N (1-24) as the paid-run gate and sends exactly one request.
Prints only PASS/FAIL, the requested model and the served model; never
ports, tokens, keys or content.
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
PAIR_PROMPT = 'Reply with the synthetic marker contained in the tool result.'
STATE_PATH = Path.home() / '.codex/mixed-model-router/mixed-router-state.json'


def captured_item():
    return {'type': 'function_call_output', 'name': 'create_thread',
            'namespace': 'codex_app',
            'output': '<codex_delegation>' + MARKER + '</codex_delegation>'}


def captured_agent_message():
    return {'type': 'agent_message', 'author': '/root/probe_child', 'recipient': '/root',
            'content': [{'type': 'input_text', 'text': OPAQUE_MARKER},
                        {'type': 'encrypted_content', 'encrypted_content': CIPHER_MARKER}]}


def shape_items(shape):
    """Synthetic history for one shape; a replayed pair carries MARKER in its output only."""
    if shape == 'standalone':
        return [captured_item(), captured_agent_message()]
    if shape == 'custom_pair':
        return [{'type': 'custom_tool_call', 'call_id': 'call_probe_pair',
                 'name': 'probe_exec', 'input': 'cat note.txt'},
                {'type': 'custom_tool_call_output', 'call_id': 'call_probe_pair',
                 'output': 'note.txt: ' + MARKER}]
    return [{'type': 'apply_patch_call', 'call_id': 'call_probe_pair', 'status': 'completed',
             'operation': {'type': 'update_file', 'path': 'note.txt',
                           'diff': '@@\n-draft\n+final\n'}},
            {'type': 'apply_patch_call_output', 'call_id': 'call_probe_pair',
             'status': 'completed', 'output': 'Done. ' + MARKER}]


class _OfflineKey:
    def key_for(self, provider_id=None):
        return 'offline-probe-key'


def prepare_offline(model, shape):
    provider = providers.select(model, '/responses', [])
    assert type(provider).__name__ == 'ExternalResponsesProvider', 'wrong provider'
    prepared = provider.prepare(
        model, '/responses', {'model': model, 'input': shape_items(shape)},
        b'raw', {}, _OfflineKey())
    data = json.loads(prepared.body)['input']
    if shape != 'standalone':
        sent = shape_items(shape)
        assert [i.get('type') for i in data] == [i['type'] for i in sent], 'pair types changed'
        assert data[0].get('call_id') == data[1].get('call_id') == sent[0]['call_id'], 'call_id changed'
        assert MARKER in data[1].get('output', ''), 'pair marker missing'
        assert MARKER not in PAIR_PROMPT + json.dumps(sent[0])
        return
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


def run_live(model, shape):
    """One request; returns the served model."""
    state = json.loads(STATE_PATH.read_text())
    url = ('http://127.0.0.1:' + str(state['port']) + '/' + state['token']
           + '/backend-api/codex/responses')
    prompt = LIVE_PROMPT if shape == 'standalone' else PAIR_PROMPT
    body = {'model': model, 'input': [
        {'type': 'message', 'role': 'user', 'content': prompt}, *shape_items(shape)]}
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=120) as response:
        assert response.status == 200, 'not HTTP 200'
        result = json.loads(response.read())
    text = ' '.join(block.get('text', '') for item in result.get('output', [])
                    for block in (item.get('content') or [])
                    if isinstance(block, dict))
    assert MARKER in text, 'delegation marker missing from reply'
    if shape == 'standalone':
        assert OPAQUE_MARKER in text, 'opaque-reply marker missing from reply'
    return result.get('model')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--max-calls', type=int, default=0)
    parser.add_argument('--model', default=MODEL)
    parser.add_argument('--shape', default='standalone',
                        choices=('standalone', 'custom_pair', 'apply_patch_pair'))
    args = parser.parse_args()
    if args.live and not 1 <= args.max_calls <= 24:
        print('FAIL')
        raise SystemExit('--live requires --max-calls between 1 and 24')
    try:
        if args.live:
            print('PASS', args.model, run_live(args.model, args.shape))
        else:
            prepare_offline(args.model, args.shape)
            print('PASS', args.model)
    except Exception:
        print('FAIL', args.model)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
