"""Bounded real-Codex proof of policy-selected GPT review handoffs.

Synthetic tasks only. Requires --live; candidate routing runs in this process.
To verify an installed release, run its copy of this script. No live config edits.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_router import catalogue, provider_defs, subscription_discovery, transport
from tools import probe_agent_handoffs as handoffs

PARENT, CHILD, EFFORT = 'gpt-6.1-sol', 'openai/gpt-6.1-sol', 'high'
MAX_CALLS, MAX_OUTPUT, MAX_INPUT, TIMEOUT = 12, 4096, 128 * 1024, 300


class Budget:
    """Count every actual upstream attempt, including router repairs/replays."""
    def __init__(self, send):
        self.send, self.calls = send, 0
        self.deadline = time.monotonic() + TIMEOUT
        self.lock = threading.Lock()

    def __call__(self, conn, prepared, metrics):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0 or transport.request_bytes(prepared) > MAX_INPUT:
            raise ValueError('review probe time or input budget')
        if provider_defs.is_external(prepared.provider):
            payload = json.loads(prepared.body)
            if payload.get('max_output_tokens') != MAX_OUTPUT:
                raise ValueError('review probe output budget')
        with self.lock:
            if self.calls >= MAX_CALLS:
                raise ValueError('review probe call budget')
            self.calls += 1
        conn.timeout = min(conn.timeout or remaining, remaining)
        if conn.sock is not None:
            conn.sock.settimeout(conn.timeout)
        return self.send(conn, prepared, metrics)


class ReviewProbe(handoffs.Probe):
    deadline = None
    parent_effort = child_effort = EFFORT
    native_model = PARENT
    expected_replies = set(handoffs.MARKERS[:2])
    required_final = 'SYNTH_REVIEW_HANDOFF_DONE'
    live_prompts = [
        'Synthetic review dispatch check, not a repository review or approval. '
        'Use the Codex pre-commit model policy to delegate once to a fresh '
        'read-only child named review_probe. Its complete assignment is to '
        'reply exactly SYNTH_066_INITIAL, without tools, files or delegation. '
        'Wait for its reply, then finish with SYNTH_REVIEW_HANDOFF_DONE.',
        'Give review_probe a follow-up assignment to reply exactly '
        'SYNTH_066_FOLLOWUP, without tools, files or delegation. Wait for its '
        'reply, then finish with SYNTH_REVIEW_HANDOFF_DONE.']

    @property
    def timeout(self):
        return max(0, self.deadline - time.monotonic())

    def __init__(self, *args):
        super().__init__(*args)
        version = subprocess.run([handoffs.codex_bin(), '--version'], check=True,
                                 capture_output=True, text=True, timeout=10).stdout
        version = re.search(r'\d+(?:\.\d+)+(?:[-+][\w.-]+)?', version).group()
        review = (ROOT / 'plugins/scg-review/skills/pre-commit-review/SKILL.md').read_text()
        guide = (ROOT / 'plugins/scg-subagents/skills/optimal-subagents/references/tool-guide.md').read_text()
        self.instructions = ('This is a synthetic delivery check. Apply only the model selection '
            'and handoff guidance below; do not run review steps, approve or commit.\n'
            + review.split('## Models and runtimes\n', 1)[1].split('## Step 1:', 1)[0] + '\n' + guide)
        auth = json.loads((Path.home() / '.codex/auth.json').read_text())['tokens']
        headers = {'Authorization': 'Bearer ' + auth['access_token']}
        if auth.get('account_id'):
            headers['ChatGPT-Account-Id'] = auth['account_id']
        rows = subscription_discovery.fetch_native(headers, version)
        self.catalogue_rows = {r['slug']: {**catalogue.subscription_stub(r['slug']), **r} for r in rows}
        if PARENT not in self.catalogue_rows:
            raise ValueError('review probe parent not advertised')
        self.facts.update(client_version=version, parent_model=PARENT, parent_effort=EFFORT,
                          child_model=CHILD, child_effort=EFFORT, selections=[], served=[])
        self.scope_ready = False

    def forward(self, body, headers, path='/responses'):
        if body.get('model') not in (PARENT, CHILD) or path.endswith('/compact'):
            raise ValueError('review probe unexpected route')
        if not self.scope_ready:
            # A static client catalogue skips discovery. Bind current native
            # membership to this candidate using the real client's identity.
            url = self.upstream.rsplit('/', 1)[0] + '/models?client_version=' + self.facts['client_version']
            request = urllib.request.Request(url, headers=dict(headers))
            with urllib.request.urlopen(request, timeout=4) as response:
                models = json.loads(response.read(subscription_discovery.MAX_BYTES + 1))['models']
            if not any(row['slug'] == PARENT for row in models):
                raise ValueError('review probe parent discovery failed')
            self.scope_ready = True
        if body.get('model') == CHILD:
            body = {**body, 'max_output_tokens': MAX_OUTPUT}
        return super().forward(body, headers, path)

    def respond(self, body, headers, ordinal, path='/responses'):
        if body.get('model') == CHILD and body.get('reasoning', {}).get('effort') != EFFORT:
            raise ValueError('review probe child effort mismatch')
        for item in body.get('input', []):
            if item.get('type') == 'function_call' and item.get('name') == 'spawn_agent':
                try:
                    args = json.loads(item.get('arguments', '{}'))
                except ValueError:
                    continue
                if isinstance(args, dict) and args.get('task_name') == 'review_probe':
                    selection = {k: args.get(k) for k in ('model', 'reasoning_effort', 'fork_turns')}
                    selection['plaintext'] = item.get('encrypted_function_args') == []
                    if selection not in self.facts['selections']:
                        self.facts['selections'].append(selection)
        raw = super().respond(body, headers, ordinal, path)
        for frame in raw.split(b'\n\n'):
            data = handoffs.frame_data(frame)
            if not data or data == b'[DONE]':
                continue
            response = json.loads(data).get('response', {})
            served = response.get('model')
            if served and body.get('model') == CHILD:
                identity = {'model': served, 'effort': response.get('reasoning', {}).get('effort', 'unverified')}
                if identity not in self.facts['served']:
                    self.facts['served'].append(identity)
        return raw

    def verify(self):
        expected = {'model': CHILD, 'reasoning_effort': EFFORT, 'fork_turns': 'none', 'plaintext': True}
        calls = [c for c in self.facts['calls']
                 if c['name'] in ('spawn_agent', 'followup_task', 'send_message')]
        same_child = (len(calls) == 2 and calls[0]['name'] == 'spawn_agent'
                      and calls[0].get('task') == 'review_probe'
                      and calls[1]['name'] == 'followup_task'
                      and calls[1].get('target') in ('review_probe', '/root/review_probe')
                      and all(c['model'] == PARENT and c['encrypted_fields'] == 'empty' for c in calls))
        return (same_child and not self.errors and not self.facts['tool_failures']
                and not self.facts['request_failures'] and self.facts['retry_events'] == 0
                and self.facts['selections'] == [expected]
                and self.expected_replies <= set(self.facts['replies'])
                and self.facts['canonical_replay']
                and all(i['model'] == CHILD and i['effort'] in (EFFORT, 'unverified')
                        for i in self.facts['served']))

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args(argv)
    if not args.live:
        parser.error('requires --live; unit tests exercise the budgets offline')
    handoffs.PARENT, handoffs.CHILD = PARENT, CHILD
    args.codex = handoffs.codex_bin()
    args.max_live_calls = MAX_CALLS
    args.live_children = True
    args.native_only = args.lifecycle = args.installed = False
    args.wire_mode = 'lite'
    budget = Budget(transport.post_with_phases)
    ReviewProbe.deadline = budget.deadline
    try:
        with patch.object(transport, 'post_with_phases', budget):
            result = handoffs.run(args, probe_type=ReviewProbe)
        print(json.dumps({'upstream_calls': budget.calls, 'call_cap': MAX_CALLS,
                          'external_output_cap': MAX_OUTPUT, 'timeout_seconds': TIMEOUT}))
        return result
    except Exception as exc:
        print(json.dumps({'probe_error': type(exc).__name__, 'upstream_calls': budget.calls}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
