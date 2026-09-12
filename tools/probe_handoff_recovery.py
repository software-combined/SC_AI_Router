"""Real-Codex regression: bad handoffs recover within one user turn.

Default: loopback scripted responses, no credentials or paid calls. Optional
live mode has a required call cap and synthetic assignments only. Unit tests
remain network-free; run this client acceptance before handoff releases.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.probe_agent_handoffs import CHILD, MARKERS, PARENT, Probe, message, run, sse


class RecoveryProbe(Probe):
    required_final = 'SYNTH_RECOVERY_DONE'
    expected_recovered = ('spawn_agent', 'followup_task', 'send_message')
    recovery_instruction = (
        'This is an authorised negative-path handoff test with synthetic text only. '
        'First use the original collaboration tool specified below exactly once, '
        'even though this intentionally tests the wrong encrypted route. '
        'If it is rejected, correct that same call using the exposed plaintext '
        'equivalent and a readable message. After successful delivery, finish with '
        'SYNTH_RECOVERY_DONE. Do not end on the first validation error. ')
    live_prompts = [
        recovery_instruction + f'Call collaboration.spawn_agent to create plain on {CHILD}, '
        f'fork_turns none, reasoning_effort max, message "Reply exactly {MARKERS[0]}".',
        recovery_instruction + 'Call collaboration.followup_task for target plain, '
        f'message "Reply exactly {MARKERS[1]}".',
        recovery_instruction + 'Call collaboration.send_message for target plain, '
        f'message "Reply exactly {MARKERS[2]}".',
        'Use collaboration_plaintext.followup_task to wake plain. Ask it to return '
        'all three SYNTH_066 markers from its assignments. Finish with SYNTH_RECOVERY_DONE.',
        'Use collaboration.spawn_agent to create native on gpt-5.6-sol, fork_turns none, '
        'message "Reply exactly SYNTH_NATIVE_CONTROL". Finish with SYNTH_RECOVERY_DONE.']

    def respond(self, body, headers, ordinal, path='/responses'):
        if self.live and body.get('model') == PARENT:
            recovered = set(self.facts.get('recovered_tools', []))
            for item in body.get('input', []):
                if item.get('type') != 'function_call_output':
                    continue
                output = json.dumps(item.get('output'))
                if 'failed to parse function arguments' in output:
                    for name in self.expected_recovered:
                        if 'collaboration_plaintext.' + name in output:
                            recovered.add(name)
            self.facts['recovered_tools'] = sorted(recovered)
        return super().respond(body, headers, ordinal, path)

    def scripted(self, body, ordinal):
        if body.get('model') != PARENT:
            return super().scripted(body, ordinal)
        step = self.parent_calls
        self.parent_calls += 1
        self.facts['parent_requests'] = self.parent_calls
        calls = [
            ('spawn_agent', {'task_name': 'plain', 'model': CHILD, 'fork_turns': 'none',
                             'reasoning_effort': 'max', 'message': MARKERS[0]}),
            ('followup_task', {'target': '/root/plain', 'message': MARKERS[1]}),
            ('send_message', {'target': 'plain', 'message': MARKERS[2]}),
        ]
        if step < 6:
            name, arguments = calls[step // 2]
            retry = step % 2 == 1
            if retry:
                outputs = [item for item in body.get('input', [])
                           if item.get('type') == 'function_call_output'
                           and item.get('call_id') == 'call_recovery_' + str(step - 1)]
                correction = 'collaboration_plaintext.' + name
                if not outputs or not all(text in json.dumps(outputs) for text in (
                        'failed to parse function arguments', correction)):
                    raise ValueError('Codex did not return the required validation error')
                self.facts.setdefault('recovered_tools', []).append(name)
            else:
                arguments = {**arguments, 'message': 'SYNTH_OPAQUE_DO_NOT_DELIVER'}
            item = {'type': 'function_call', 'namespace': (
                'collaboration_plaintext' if retry else 'collaboration'),
                'name': name, 'id': 'fc_recovery_' + str(step),
                'call_id': 'call_recovery_' + str(step), 'arguments': json.dumps(arguments)}
            return sse([item], str(ordinal))
        if step == 6:
            item = {'type': 'function_call', 'namespace': 'collaboration_plaintext',
                'name': 'followup_task', 'id': 'fc_flush', 'call_id': 'call_flush',
                'arguments': json.dumps({'target': 'plain', 'message': 'SYNTH_FLUSH'})}
            return sse([item], str(ordinal))
        if step == 7:
            item = {'type': 'function_call', 'namespace': 'collaboration',
                'name': 'spawn_agent', 'id': 'fc_native', 'call_id': 'call_native',
                'arguments': json.dumps({'task_name': 'native', 'model': 'gpt-5.6-sol',
                    'fork_turns': 'none', 'message': 'SYNTH_OPAQUE_CONTROL'})}
            return sse([item], str(ordinal))
        return sse([message(self.required_final, str(ordinal))], str(ordinal))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', default='/Applications/ChatGPT.app/Contents/Resources/codex')
    parser.add_argument('--wire-mode', choices=('classic', 'lite'), default='lite')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--installed', action='store_true')
    parser.add_argument('--max-live-calls', type=int, default=0)
    args = parser.parse_args()
    args.live_children = args.live
    args.lifecycle = args.native_only = False
    raise SystemExit(run(args, probe_type=RecoveryProbe))
