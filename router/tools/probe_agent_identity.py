"""Zero-paid real-Codex V1 child-ID/header correlation gate.

Two same-model children overlap against a scripted loopback upstream. No auth,
live state or tool content is retained; only synthetic UUID mappings are printed.
"""
import argparse
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_router.catalogue import external_entry, subscription_stub
from ai_router.registry import by_slug
from ai_router.request_evidence import thread_id as uuid_value
from tools import probe_agent_handoffs as handoffs

MODEL = 'deepseek/deepseek-v4.1-flash-1017'
CALLS = ('call_identity_a', 'call_identity_b')


class IdentityProbe(handoffs.Probe):
    identifies_threads = True
    multi_agent_v2 = False
    required_final = 'SYNTH_IDENTITY_DONE'
    expected_replies = set()
    parent_effort = child_effort = 'low'
    live_prompts = ['Synthetic test: spawn two fresh children and wait for both.']

    def __init__(self, *args):
        super().__init__(*args)
        self.catalogue_rows = {MODEL: external_entry(by_slug(MODEL)),
                              'gpt-5.6-sol': subscription_stub('gpt-5.6-sol')}
        self.catalogue_rows[MODEL].update(multi_agent_version='v1', use_responses_lite=False)
        self.child_threads, self.returned_ids = set(), {}
        self.children_ready = threading.Event()
        self.facts.update(multi_agent_version='v1', parent_model=MODEL, child_model=MODEL,
                          requested_effort='low', upstream_calls=0, child_headers=[])

    def tool(self, body, name):
        containers = [body, *(i for i in body.get('input', [])
                              if i.get('type') in ('additional_tools', 'tool_search_output'))]
        for container in containers:
            for declaration in container.get('tools', []):
                if declaration.get('type') == 'namespace':
                    for tool in declaration.get('tools', []):
                        if tool.get('name') == name:
                            if declaration['name'] != 'multi_agent_v1':
                                raise ValueError('not the V1 tool surface')
                            self.facts.setdefault('declared_tools', {})[name] = {
                                'namespace': declaration['name'],
                                'fields': list(tool.get('parameters', {}).get('properties', {}))}
                            return declaration['name']
        raise ValueError('required V1 tool not declared')

    def call(self, body, name, arguments, ident):
        namespace = self.tool(body, name)
        return {'type': 'function_call', 'name': name, 'id': 'fc_' + ident,
                'call_id': ident, 'arguments': json.dumps(arguments), 'namespace': namespace}

    def respond(self, body, headers, ordinal, path='/responses'):
        headers = {k.lower(): v for k, v in headers.items()}
        thread = uuid_value(headers.get('thread-id'))
        if body.get('model') != MODEL or not thread or path.endswith('/compact') or ordinal > 8:
            raise ValueError('unexpected identity probe request')
        if thread != self.parent_thread_id:
            parent = uuid_value(headers.get('x-codex-parent-thread-id'))
            if parent != self.parent_thread_id:
                raise ValueError('child parent header mismatch')
            with self.lock:
                self.child_threads.add(thread)
                self.facts['child_headers'].append({'thread_id': thread, 'parent_thread_id': parent})
                if len(self.child_threads) == 2:
                    self.children_ready.set()
            if not self.children_ready.wait(10):
                raise ValueError('same-model children did not overlap')
            return handoffs.sse([handoffs.message('SYNTH_CHILD_DONE', str(ordinal))], str(ordinal))
        self.parent_calls += 1
        self.facts['parent_requests'] = self.parent_calls
        if self.parent_calls == 1:
            search = next((t for t in body.get('tools', []) if t.get('type') == 'tool_search'), None)
            if search:
                self.facts['search_fields'] = list(search.get('parameters', {}).get('properties', {}))
                return handoffs.sse([{'type': 'tool_search_call', 'id': 'ts_identity',
                    'call_id': 'call_identity_search', 'execution': 'client',
                    'arguments': {'query': 'multi_agent spawn_agent wait_agent'}}], str(ordinal))
        for item in body.get('input', []):
            if item.get('type') == 'function_call_output' and item.get('call_id') in CALLS:
                output = item.get('output')
                if isinstance(output, str):
                    output = json.loads(output)
                if not isinstance(output, dict) or not uuid_value(output.get('agent_id')):
                    raise ValueError('V1 spawn returned no UUID')
                self.returned_ids[item['call_id']] = output['agent_id']
        if not self.facts.get('spawned'):
            items = [self.call(body, 'spawn_agent', {'model': MODEL, 'reasoning_effort': 'low',
                'fork_context': False, 'message': 'Reply SYNTH_CHILD_DONE without tools.'}, ident)
                     for ident in CALLS]
            self.facts['spawned'] = True
        elif not self.facts.get('waited'):
            if len(self.returned_ids) != 2:
                raise ValueError('two spawn results not replayed')
            items = [self.call(body, 'wait_agent', {'targets': list(self.returned_ids.values()),
                'timeout_ms': 10000}, 'call_identity_wait')]
            self.facts['waited'] = True
        else:
            items = [handoffs.message(self.required_final, str(ordinal))]
        return handoffs.sse(items, str(ordinal))

    def verify(self):
        matched = (len(self.returned_ids) == len(self.child_threads) == 2
                   and set(self.returned_ids.values()) == self.child_threads)
        self.facts.update(returned_agent_ids=self.returned_ids, exact_mapping=matched,
                          concurrent_children=self.children_ready.is_set())
        return (matched and self.children_ready.is_set()
                and not self.errors and not self.facts['tool_failures'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', default=handoffs.codex_bin())
    args = parser.parse_args()
    args.live = args.live_children = args.lifecycle = args.native_only = False
    args.max_live_calls, args.wire_mode = 0, 'classic'
    handoffs.PARENT = handoffs.CHILD = MODEL
    return handoffs.run(args, IdentityProbe)


if __name__ == '__main__':
    raise SystemExit(main())
