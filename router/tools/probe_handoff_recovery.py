"""Real-Codex negative proof: an encrypted handoff ends once before delivery.

Scripted loopback only, no credentials or paid calls. The shared router guard
provides the same typed refusal the production relay renders as response.failed.
Per-tool recovery is a Codex contract; this probe requires a terminal rejection.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_router.errors import ResponseRejected
from tools.appserver_probe import codex_bin
from tools.probe_agent_handoffs import CHILD, PARENT, Probe, run, sse


class RejectionProbe(Probe):
    expected_parent_failure = True

    def scripted(self, body, ordinal):
        if body.get('model') != PARENT:
            self.facts['unexpected_child_requests'] = self.facts.get('unexpected_child_requests', 0) + 1
            raise ValueError('rejected handoff started a child')
        self.parent_calls += 1
        self.facts['parent_requests'] = self.parent_calls
        return sse([{'type': 'function_call', 'namespace': 'collaboration',
            'name': 'spawn_agent', 'id': 'fc_rejected', 'call_id': 'call_rejected',
            'encrypted_function_args': ['message'], 'arguments': json.dumps({
                'task_name': 'plain', 'model': CHILD, 'fork_turns': 'none',
                'reasoning_effort': 'max', 'message': 'SYNTH_OPAQUE_DO_NOT_DELIVER'})}], str(ordinal))

    def respond(self, *args, **kwargs):
        try:
            return super().respond(*args, **kwargs)
        except ResponseRejected as exc:
            self.facts['rejections'] = self.facts.get('rejections', 0) + 1
            return ('event: response.failed\ndata: ' + json.dumps({
                'type': 'response.failed', 'response': exc.body()}) + '\n\n').encode()

    def negotiation_failure(self, event, failure):
        if not isinstance(failure, dict):
            return False
        message = failure.get('message', '')
        if (failure.get('codexErrorInfo') in ('invalidPrompt', 'other')
                and 'blocked before delivery' in message
                and 'SpawnAgentArgs' not in message and 'failed to parse' not in message):
            self.facts['typed_rejection_received'] = True
            self.facts['argument_parse_error'] = False
            return True
        return False

    def verify(self):
        self.facts['parent_requests'] = self.parent_calls
        return (self.parent_calls == 1 and self.facts.get('rejections') == 1
                and self.facts.get('typed_rejection_received')
                and not self.facts.get('unexpected_child_requests')
                and not self.errors and not self.facts['tool_failures'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', default=codex_bin())
    parser.add_argument('--wire-mode', choices=('classic', 'lite'), default='lite')
    args = parser.parse_args()
    args.live = args.live_children = args.installed = args.lifecycle = args.native_only = False
    args.max_live_calls = 0
    raise SystemExit(run(args, probe_type=RejectionProbe))
