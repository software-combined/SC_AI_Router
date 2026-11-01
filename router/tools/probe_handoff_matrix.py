"""Real-Codex handoff proofs; scripted loopback by default.

--live permits the four route cases, each capped at 12 actual upstream attempts,
4,096 tokens on every external request and five minutes. Failure stops the matrix.
--live --case legacy-native runs the router-upgrade case from probe_desktop_handoff
under the same caps. Child receipts prove each recipient read its brief; handoffs
are scored by the client-side call and its message shape, never by the upstream
namespace. No live configuration is edited.
"""
import argparse
import io
import json
import logging
from pathlib import Path
import re
import sys
import threading
import time
from types import SimpleNamespace
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_router import (agent_handoffs, catalogue, history_items, provider_defs, providers,
                       subscription_discovery)
from ai_router.registry import by_slug
from tools import probe_agent_handoffs as handoffs
from tools.probe_review_handoffs import MAX_CALLS, MAX_OUTPUT

CASES = ('native-native', 'native-external', 'external-native', 'external-external')
LEGACY = 'legacy-native'
MARKERS = ('SYNTH_MATRIX_INITIAL', 'SYNTH_MATRIX_FOLLOWUP')
SAFE = re.compile(r'[\w.:/@-]{1,96}')
ROUTER_EVENTS = frozenset(('handoff_observed', 'attempt_ledger', 'request_started', 'request_completed',
                           'request_failed', 'request_rejected', 'turn_refused', 'upstream_rejected'))
ROW_FIELDS = ('event', 'request_id', 'router_version', 'model', 'reasoning_effort', 'request_bytes', 'sends',
              'status', 'code', 'outcome', 'served_model', 'tool', 'parameter', 'phase', 'declaration',
              'schema_mode', 'message_shape', 'marker_rejected', 'guard_rejected', 'restoration_rejected')


def safe_value(value):
    """A number, flag or identifier-like string; anything else becomes 'other'."""
    if value is None or isinstance(value, (int, float)):
        return value
    return value if isinstance(value, str) and SAFE.fullmatch(value) else 'other'


def safe_row(row, turn):
    """The whitelisted, content-free fields of one router log row."""
    kept = {key: safe_value(row[key]) for key in ROW_FIELDS if key in row}
    for key in ('upstream', 'client'):
        if isinstance(row.get(key), dict):
            kept[key] = {field: safe_value(row[key].get(field)) for field in ('namespace', 'marker', 'arguments')}
    return {'turn': turn, **kept}


def tally(rows, field):
    """Per-turn counts of row[field], or of field(row) when it is callable."""
    totals = {}
    for row in rows:
        value = str(field(row) if callable(field) else row.get(field))
        turn = totals.setdefault(f"turn{row['turn']}", {})
        turn[value] = turn.get(value, 0) + 1
    return totals


class RouterRows(logging.Handler):
    """Content-free in-process router events for one probe."""
    def __init__(self, probe):
        super().__init__()
        self.probe = probe

    def emit(self, record):
        try:
            row = json.loads(record.getMessage())
        except ValueError:
            return
        if isinstance(row, dict) and row.get('event') in ROUTER_EVENTS:
            self.probe.router_rows.append(safe_row(row, self.probe.turn_index()))


class MatrixProbe(handoffs.Probe):
    identifies_threads = persist = True
    required_final = 'SYNTH_MATRIX_PARENT_DONE'
    markers = MARKERS
    expected_replies = set(MARKERS)
    agents = {'/root/matrix_child': 'child'}
    native, external = 'gpt-6.1-sol', 'openai/gpt-6.1-sol'
    parent_effort = child_effort = 'high'
    wire_mode = 'lite'
    codex, deadline = handoffs.codex_bin(), None

    @property
    def timeout(self):
        return max(0, self.deadline - time.monotonic())

    @property
    def routes(self):
        """Each client role's requested model and effort."""
        return {'parent': (self.parent, self.parent_effort), 'child': (self.child, self.child_effort)}

    def __init__(self, *args):
        super().__init__(*args)
        self.native_model = self.native
        self.parent, self.child = handoffs.PARENT, handoffs.CHILD
        self.child_agents, self.parent_calls, self.child_calls = set(), 0, 0
        self.call_ids, self.scope_ready, self.router_rows = set(), False, []
        self.receipt = threading.Event()
        self.instructions = ('Synthetic handoff test. Preserve the requested child model and effort. '
            'Use the collaboration tools for every recipient. '
            'Start fresh children with fork_turns none. Children must not use tools, files or delegation.')
        self.live_prompts = [
            f'Delegate to one fresh child named matrix_child on {self.child}, reasoning effort '
            f'{self.child_effort}. Its assignment is to reply exactly {MARKERS[0]} without tools. '
            'Wait for its reply and finish with ' + self.required_final + '.',
            f'Give matrix_child a follow-up assignment to reply exactly {MARKERS[1]} without tools. '
            'Wait for its reply and finish with ' + self.required_final + '.']
        self.facts.update(parent_model=self.parent, child_model=self.child,
            parent_effort=self.parent_effort, child_effort=self.child_effort, selections=[], served=[],
            child_receipts=[], receipt_roles=[], client_calls=[], rejections=[],
            observed_declarations={role: [] for role in self.routes},
            **{role + '_requests': 0 for role in self.routes})
        self.facts.update(assigned_markers=[], peer_shapes=[], child_reply_shapes=[], terminals=[], parent_tool_methods=[])
        if self.live:
            raise SystemExit('Native live matrix probes are retired; run the offline synthetic matrix.')
        else:
            native = {**catalogue.subscription_stub(self.native),
                'supported_reasoning_levels': [{'effort': 'high', 'description': 'Synthetic fixture'}]}
            self.catalogue_rows = {self.native: native,
                self.external: catalogue.external_entry(by_slug(self.external))}
            for row in self.catalogue_rows.values():
                row.update(multi_agent_version='v2', use_responses_lite=self.wire_mode == 'lite')

    def role(self, headers):
        headers = {key.lower(): value for key, value in headers.items()}
        ident = headers.get('thread-id')
        metadata = json.loads(headers.get('x-codex-turn-metadata', '{}'))
        agent = metadata.get('agent_name')
        if ident == self.parent_thread_id and agent == '/root':
            return 'parent'
        if (ident and ident != self.parent_thread_id and agent in self.agents
                and headers.get('x-codex-parent-thread-id') == self.parent_thread_id):
            self.child_agents.add((ident, agent))
            return self.agents[agent]
        raise ValueError('matrix request has no matching client thread identity')

    def turn_index(self):
        """1 + the parent turns the client has reported complete."""
        parent = getattr(self, 'parent_thread_id', None)
        return 1 + sum(row.get('thread') == parent for row in self.facts.get('completed_turns', []))

    def respond(self, body, headers, ordinal, path='/responses'):
        self.record_input_facts(body)
        role = self.role(headers)
        declaration = ('lite' if any(item.get('type') == 'additional_tools'
            and item.get('role') == 'developer' for item in body.get('input', []))
            else 'classic' if body.get('tools') else 'none')
        if declaration not in self.facts['observed_declarations'][role]:
            self.facts['observed_declarations'][role].append(declaration)
        expected, effort = self.routes[role]
        if (body.get('model') != expected or body.get('reasoning', {}).get('effort') != effort
                or path.endswith('/compact')):
            raise ValueError('matrix model or effort mismatch')
        self.facts[role + '_requests'] += 1
        for item in body.get('input', []):
            if item.get('type') == 'agent_message':
                text = '\n'.join(b.get('text', '') for b in item.get('content', [])
                    if b.get('type') == 'input_text' and isinstance(b.get('text'), str))
                self.facts['peer_shapes'].append({'role': role, 'request': ordinal,
                    'markers': [m for m in self.markers if m in text],
                    'new_task': 'NEW_TASK' in text, 'final_answer': 'FINAL_ANSWER' in text,
                    'recoverable_sidecar': history_items.recoverable_agent_message(item) is not None})
        if sum(self.facts[name + '_requests'] for name in self.routes) > MAX_CALLS:
            raise ValueError('matrix client request cap')
        if role == 'parent':
            for item in body.get('input', []):
                if item.get('type') == 'function_call' and item.get('call_id') in self.call_ids:
                    self.facts['canonical_replay'] |= item.get('namespace') == 'collaboration'
        if self.live:
            if not self.scope_ready:
                url = self.upstream.rsplit('/', 1)[0] + '/models?client_version=' + self.version
                with urllib.request.urlopen(urllib.request.Request(url, headers=dict(headers)), timeout=4) as response:
                    rows = json.loads(response.read(subscription_discovery.MAX_BYTES + 1))['models']
                if not any(row['slug'] == self.native for row in rows):
                    raise ValueError('matrix native discovery failed')
                self.scope_ready = True
            if expected == self.external:
                body = {**body, 'max_output_tokens': MAX_OUTPUT}
            raw = self.forward(body, headers, path, role)
        else:
            raw = self.scripted_response(body, headers, ordinal, role)
        self.observe(raw, role)
        return raw

    def forward(self, body, headers, path='/responses', role=None):
        try:
            return super().forward(body, headers, path)
        except urllib.error.HTTPError as exc:
            try:
                code = json.loads(exc.read(65536))['error']['code']
            except (ValueError, KeyError, TypeError, OSError):
                code = None
            self.facts['rejections'].append({'turn': self.turn_index(), 'role': role,
                                             'status': exc.code, 'code': safe_value(code)})
            raise

    def scripted_response(self, body, headers, ordinal, role):
        provider = (providers.ExternalResponsesProvider(provider_defs.OPENROUTER)
                    if body['model'] == self.external else providers.SubscriptionProvider())
        # A mixed install: the external key resolves, so every brief is readable.
        prepared = provider.prepare(body['model'], '/responses', body, json.dumps(body).encode(),
            headers, SimpleNamespace(key_for=lambda _: 'synthetic-key', key_missing=lambda _: None))
        if role == 'child':
            self.child_calls += 1
            text = '\n'.join(block.get('text', '') for item in body.get('input', [])
                if item.get('type') == 'agent_message' for block in item.get('content', [])
                if block.get('type') == 'input_text')
            if MARKERS[min(self.child_calls - 1, 1)] not in text:
                raise ValueError('scripted child did not receive its readable assignment')
            items = [handoffs.message(MARKERS[min(self.child_calls - 1, 1)], str(ordinal))]
        else:
            step = self.parent_calls
            self.parent_calls += 1
            if step % 2:
                if not self.receipt.wait(5):
                    raise ValueError('scripted child reply missing')
                self.receipt.clear()
                items = [handoffs.message(self.required_final, str(ordinal))]
            else:
                name = 'spawn_agent' if step == 0 else 'followup_task'
                args = ({'task_name': 'matrix_child', 'model': self.child, 'fork_turns': 'none',
                         'reasoning_effort': self.child_effort} if step == 0 else {'target': 'matrix_child'})
                args['message'] = MARKERS[min(step // 2, 1)]
                items = [{'type': 'function_call', 'namespace': 'collaboration',
                    'name': name, 'id': 'fc_' + str(ordinal), 'call_id': 'call_' + str(ordinal),
                    'arguments': json.dumps(args)}]
        source = io.BytesIO(handoffs.sse(items, str(ordinal)))
        source.status = 200
        source.getheader = lambda name, default='': 'text/event-stream'
        return b''.join(provider.adapt(source, prepared.tool_names))

    def observe(self, raw, role):
        turn = self.turn_index()
        for part in raw.replace(b'\r\n', b'\n').split(b'\n\n'):
            data = handoffs.frame_data(part)
            if not data or data == b'[DONE]':
                continue
            event = json.loads(data)
            if event.get('type') in ('response.completed', 'response.incomplete', 'response.failed'):
                response = event.get('response', {})
                reason = (response.get('incomplete_details') or {}).get('reason')
                error = response.get('error') if isinstance(response.get('error'), dict) else {}
                self.facts['terminals'].append({'turn': turn, 'role': role, 'type': event['type'], 'code': safe_value(error.get('code')),
                    'reason': reason if reason in ('max_output_tokens', 'interrupted', 'content_filter') else None})
                if event['type'] == 'response.failed':
                    self.facts['rejections'].append({'turn': turn, 'role': role, 'status': 200, 'code': safe_value(error.get('code'))})
            if event.get('type') == 'response.completed' and self.live:
                response = event.get('response', {})
                self.facts['served'].append({'role': role, 'model': safe_value(response.get('model', 'unverified')),
                    'effort': safe_value(response.get('reasoning', {}).get('effort', 'unverified'))})
            if event.get('type') != 'response.output_item.done':
                continue
            item = event.get('item', {})
            if role == 'parent' and item.get('type') == 'function_call':
                name = item.get('name')
                self.facts['parent_tool_methods'].append(name if name in
                    ('spawn_agent', 'send_message', 'followup_task', 'wait_agent', 'list_agents', 'interrupt_agent') else 'other')
                if name in agent_handoffs.HANDOFF_TOOLS:
                    marker = item.get('encrypted_function_args', 'absent')
                    self.facts['client_calls'].append({'turn': turn, 'tool': name,
                        'namespace': 'canonical' if item.get('namespace') == agent_handoffs.NATIVE_NAMESPACE else 'other',
                        'marker': 'absent' if marker == 'absent' else 'empty' if marker == [] else 'nonempty',
                        'message_shape': agent_handoffs.message_shape(item)})
            if role == 'parent' and item.get('type') == 'function_call' and item.get('name') in ('spawn_agent', 'followup_task'):
                args = json.loads(item['arguments'])
                self.call_ids.add(item['call_id'])
                self.facts['selections'].append({'tool': item['name'],
                    **{key: safe_value(args[key]) for key in ('model', 'reasoning_effort', 'fork_turns') if key in args},
                    'plaintext': item.get('encrypted_function_args') == []})
                self.facts['assigned_markers'].append({'tool': item['name'],
                    'markers': [m for m in self.markers if m in str(args.get('message', ''))]})
            if role != 'parent' and item.get('type') == 'message':
                text = ''.join(block.get('text', '') for block in item.get('content', []))
                self.facts['child_reply_shapes'].append({'markers': [m for m in self.markers if m in text],
                    'exact': text.strip() in self.markers})
                for marker in self.markers:
                    if text.strip() == marker:
                        self.facts['child_receipts'].append(marker)
                        self.facts['receipt_roles'].append([marker, role])
                        self.facts['replies'].append(marker)
                        self.receipt.set()

    def verify(self):
        stored = set()
        for path in (self.home / 'sessions').rglob('*.jsonl'):
            for line in path.read_text().splitlines():
                entry = json.loads(line).get('payload', {})
                if (entry.get('type') == 'function_call' and entry.get('namespace') == 'collaboration'
                        and entry.get('call_id') in self.call_ids):
                    stored.add(entry['call_id'])
        self.facts['persisted_canonical_replay'] = len(stored) == 2 and stored == self.call_ids
        expected = [{'tool': 'spawn_agent', 'model': self.child, 'reasoning_effort': self.child_effort,
                     'fork_turns': 'none', 'plaintext': True}, {'tool': 'followup_task', 'plaintext': True}]
        self.facts['distinct_child_agent'] = len(self.child_agents) == 1
        identities = all(row['model'] in ('unverified', self.child if row['role'] == 'child' else self.parent)
                         and row['effort'] in ('unverified', self.child_effort if row['role'] == 'child' else self.parent_effort)
                         for row in self.facts['served'])
        return (not self.errors and not self.facts['tool_failures'] and identities
                and not self.facts['request_failures'] and self.facts['retry_events'] == 0
                and self.facts['selections'] == expected and self.facts['canonical_replay']
                and self.facts['persisted_canonical_replay'] and self.facts['distinct_child_agent']
                and set(self.facts['child_receipts']) == set(self.markers))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--wire-mode', choices=('classic', 'lite'), default='lite',
                        help='Scripted fixture only; live uses the real client catalogue.')
    parser.add_argument('--case', choices=(*CASES, LEGACY, 'all'), default='all')
    parser.add_argument('--native', default=MatrixProbe.native)
    parser.add_argument('--external', default=MatrixProbe.external)
    parser.add_argument('--native-effort', default='high')
    parser.add_argument('--external-effort', default='high')
    parser.add_argument('--record', type=Path, help='Append each case\'s content-free record here.')
    args = parser.parse_args(argv)
    external = by_slug(args.external)
    if by_slug(args.native) is not None or external is None or not provider_defs.is_external(external.provider):
        parser.error('native and external must name their respective catalogue routes')
    args.codex = MatrixProbe.codex
    args.max_live_calls = MAX_CALLS
    args.live_children = args.live
    args.native_only = args.lifecycle = args.installed = False
    from tools.probe_desktop_handoff import CaseProbe, run_case, run_legacy  # That module builds on this one.
    if args.case == LEGACY:
        if not args.live:
            parser.error('legacy-native requires --live; unit tests exercise it offline')
        return run_legacy(args)
    for case in CASES if args.case == 'all' else (args.case,):
        rows = {'native': args.native, 'external': args.external}
        efforts = {'native': args.native_effort, 'external': args.external_effort}
        parent, child = case.split('-')
        handoffs.PARENT, handoffs.CHILD = rows[parent], rows[child]
        CaseProbe.native, CaseProbe.external, CaseProbe.wire_mode = args.native, args.external, args.wire_mode
        CaseProbe.parent_effort, CaseProbe.child_effort = efforts[parent], efforts[child]
        if run_case(args, CaseProbe, case, 'in-process'):
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
