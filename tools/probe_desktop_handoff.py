"""Offline handoff case definitions and bounded diagnostic regressions.

Native live entry points are retired and refused before profile loading or
credential handling. Historical case definitions below describe earlier
measurements, not a supported live workflow. Use the offline unit suite.
"""
import argparse
import contextlib
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_router import attempt_policy, provider_defs, subscription_discovery, subscription_fallback, transport
from ai_router.credentials import Credentials
from ai_router.events import LOG
from tools import probe_agent_handoffs as handoffs
from tools.probe_handoff_matrix import LEGACY, ROUTER_EVENTS, MatrixProbe, RouterRows, safe_row, tally
from tools.probe_review_handoffs import Budget, MAX_CALLS, MAX_INPUT, MAX_OUTPUT, TIMEOUT

PARENT, CHILD = 'gpt-6.1-sol', 'openai/gpt-6.1-sol'
LEGACY_MARKERS = ('SYNTH_LEGACY_R1', 'SYNTH_LEGACY_R2', 'SYNTH_LEGACY_R3')
NATIVE_INPUT = 512 * 1024  # Real desktop parents sent 167-413 KB.
MARKETPLACE = 'scg-agent-plugins'
REFUSAL_FLAGS = ('marker_rejected', 'guard_rejected', 'restoration_rejected')
READABLE_CALL = ('canonical', 'empty', 'readable')


class CaseBudget(Budget):
    """Every upstream send, router repairs included, with a per-route input cap."""
    exhausted = None

    def admit(self, external, size, payload, cost=1):
        with self.lock:
            reason = ('time' if self.deadline <= time.monotonic()
                      else 'input' if size > (MAX_INPUT if external else NATIVE_INPUT)
                      else 'output' if external and payload.get('max_output_tokens') != MAX_OUTPUT
                      else 'call' if self.calls + cost > MAX_CALLS else None)
            if reason:
                self.exhausted = self.exhausted or reason
                raise ValueError(f'case {reason} budget')
            self.calls += cost

    def __call__(self, conn, prepared, metrics):
        external = provider_defs.is_external(prepared.provider)
        self.admit(external, transport.request_bytes(prepared), json.loads(prepared.body) if external else {})
        conn.timeout = min(conn.timeout or TIMEOUT, max(.01, self.deadline - time.monotonic()))
        if conn.sock is not None:
            conn.sock.settimeout(conn.timeout)
        return self.send(conn, prepared, metrics)


def outcome(passed, probe, budget):
    """One verdict per case; nothing is retried blind."""
    if probe.refusals():
        return 'refused'
    if budget.exhausted in ('call', 'input', 'output'):
        return 'inconclusive_budget'
    if budget.exhausted == 'time' or time.monotonic() >= budget.deadline:
        return 'inconclusive_time'
    if probe.facts.get('setup_failed'):
        return 'setup_failed'
    if passed:
        return 'passed'
    return 'refused' if probe.facts['rejections'] else 'failed'


def emit(record, path=None):
    text = json.dumps(record)
    print(text, flush=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as records:
            records.write(text + '\n')
    return 0 if record['outcome'] == 'passed' else 1


class CaseProbe(MatrixProbe):
    """A MatrixProbe whose verdict and evidence form one content-free record."""
    budget = None

    @classmethod
    def patches(cls, probes):
        return ()

    def gates(self):
        """Named pass gates; the four route cases keep MatrixProbe.verify instead."""
        return {}

    def refusals(self):
        """Router handoff refusals and upstream rejections; a spent budget is not one."""
        found = [flag for row in self.router_rows for flag in REFUSAL_FLAGS if row.get(flag) is True]
        found += [row.get('code') or row['event'] for row in self.router_rows
                  if row['event'] == 'upstream_rejected' or str(row.get('code')).startswith('HANDOFF_')]
        return found + [row['code'] for row in self.facts['rejections'] if str(row['code']).startswith('HANDOFF_')]

    def readable(self, calls):
        """Every client-side handoff is canonical, marked [] and readable, whatever went upstream."""
        return all((call['namespace'], call['marker'], call['message_shape']) == READABLE_CALL for call in calls)

    def record(self, case, target, result, budget, seconds, sends):
        gates = self.gates()  # Installed daemon readback can invalidate the earlier client verification.
        passed = result == 0 and all(gates.values()) and sends <= MAX_CALLS
        handoff = [row for row in self.router_rows if row['event'] == 'handoff_observed' and row.get('phase') in ('done', 'json')]
        return {'case': case, 'target': target, 'outcome': outcome(passed, self, budget),
            'client_version': self.facts.get('client_version'), 'seconds': round(seconds, 1),
            'upstream_sends': sends, 'forwarded_requests': self.live_calls, 'attempt_cap': MAX_CALLS,
            'requested': {role: {'model': model, 'effort': effort} for role, (model, effort) in self.routes.items()},
            'served': self.facts['served'], 'receipts': self.facts['receipt_roles'], 'gates': gates,
            'replay': {key: self.facts.get(key) for key in ('canonical_replay', 'persisted_canonical_replay', 'distinct_child_agent')},
            'client_calls': self.facts['client_calls'], 'message_shapes': tally(self.facts['client_calls'], 'message_shape'),
            'router_message_shapes': tally(handoff, 'message_shape'),
            'router_upstream_namespaces': tally(handoff, lambda row: (row.get('upstream') or {}).get('namespace')),
            'router_handoffs': handoff, 'refusals': sorted(set(self.refusals())), 'rejections': self.facts['rejections'],
            'router_failures': [row for row in self.router_rows if row['event'] in ('request_failed', 'upstream_rejected', 'turn_refused')],
            'selections': self.facts['selections'], 'request_bytes': self.facts.get('request_bytes', []),
            'unmatched_requests': self.facts.get('unmatched_requests', 0), 'setup_failed': self.facts.get('setup_failed'),
            'errors': self.errors, 'tool_failures': self.facts['tool_failures'],
            'request_failures': self.facts['request_failures'], 'retry_events': self.facts['retry_events']}


class LegacyProbe(CaseProbe):
    """U2: one thread across a simulated router upgrade, stock briefs then readable ones."""
    markers = LEGACY_MARKERS
    expected_replies = set(LEGACY_MARKERS)
    agents = {'/root/legacy_native': 'child', '/root/legacy_external': 'external'}
    external = 'deepseek/deepseek-v4.1-flash-1017'

    @property
    def routes(self):
        return {'parent': (self.parent, self.parent_effort), 'child': (self.parent, 'low'),
                'external': (self.external, 'low')}

    @classmethod
    def patches(cls, probes):
        return (legacy_gate(probes),)

    def __init__(self, *args):
        super().__init__(*args)
        self.facts.update(gate_off_lookups=0, child_briefs=[])
        (first, follow, fresh), final = self.markers, self.required_final
        self.live_prompts = [
            f'Delegate to one fresh child named legacy_native on {self.parent}, reasoning effort low. Its '
            f'assignment is to reply exactly {first} without tools. Wait for its reply and finish with {final}.',
            f'Give legacy_native a follow-up assignment to reply exactly {follow} without tools. Also delegate '
            f'to one fresh child named legacy_external on {self.external}, reasoning effort low, whose '
            f'assignment is to reply exactly {fresh} without tools. Wait for both replies and finish with {final}.']

    def gate_off(self):
        """Turn 1 is the pre-upgrade router: no external key, so the stock encrypted contract."""
        return self.turn_index() == 1

    def turn_one_ready(self):
        spawns = [call['message_shape'] for call in self.facts['client_calls']
                  if call['turn'] == 1 and call['tool'] == 'spawn_agent']
        return spawns == ['ciphertext'] and [self.markers[0], 'child'] in self.facts['receipt_roles']

    def respond(self, body, headers, ordinal, path='/responses'):
        role, turn = self.role(headers), self.turn_index()
        if role != 'parent':
            # Which delivered briefs were opaque, never their text.
            self.facts['child_briefs'].append({'turn': turn, 'role': role, 'opaque': [
                any(block.get('type') == 'encrypted_content' for block in item.get('content', []))
                for item in body.get('input', []) if item.get('type') == 'agent_message']})
        elif turn > 1 and not self.turn_one_ready():
            self.facts['setup_failed'] = 'turn 1 left no ciphertext spawn with receipt 1'
            raise ValueError('legacy turn 1 precondition failed')
        return super().respond(body, headers, ordinal, path)

    def verify(self):
        return all(self.gates().values())

    def gates(self):
        calls = [call for call in self.facts['client_calls'] if call['turn'] == 2]
        natives = {ident for ident, agent in self.child_agents if self.agents[agent] == 'child'}
        first, follow, fresh = self.markers
        self.facts['gates'] = gates = {
            'gate_simulated': self.facts['gate_off_lookups'] > 0,
            'turn1_ciphertext_spawn_and_receipt': self.turn_one_ready(),
            'turn2_parent_accepted': not any(row['turn'] == 2 and row['role'] == 'parent' for row in self.facts['rejections']),
            'turn2_readable_calls': {'spawn_agent', 'followup_task'} <= {call['tool'] for call in calls} and self.readable(calls),
            'receipts_once': sorted(map(tuple, self.facts['receipt_roles'])) == [(first, 'child'), (follow, 'child'), (fresh, 'external')],
            'same_native_child': len(natives) == 1,
            # Turn 1's native brief may be opaque; every later brief must be readable.
            'children_read_briefs': all(not any(row['opaque']) if row['role'] == 'external'
                                        else row['turn'] == 1 or row['opaque'][-1:] == [False] for row in self.facts['child_briefs']),
            'no_refusals': not self.refusals(),
            'no_errors': not (self.errors or self.facts['tool_failures'] or self.facts['request_failures']
                              or self.facts['retry_events'])}
        return gates


def legacy_gate(probes):
    """Patch the router's external-key lookup: absent until the first parent turn completes."""
    lookup = Credentials.key_missing

    def key_missing(credentials, provider_id):
        if probes and probes[0].gate_off():
            probes[0].facts['gate_off_lookups'] += 1
            return LookupError('simulated pre-upgrade router')
        return lookup(credentials, provider_id)
    return patch.object(Credentials, 'key_missing', key_missing)


def trimmed_config(text):
    """The live config cut to the model, features and SCG plugin settings."""
    live = tomllib.loads(text)
    kept = {key: live[key] for key in ('model', 'model_reasoning_effort', 'features') if key in live}
    if MARKETPLACE in live.get('marketplaces', {}):
        kept['marketplaces'] = {MARKETPLACE: live['marketplaces'][MARKETPLACE]}
    plugins = {name: entry for name, entry in live.get('plugins', {}).items() if name.endswith('@' + MARKETPLACE)}
    return {**kept, 'plugins': plugins} if plugins else kept


def toml_text(table, path=()):
    """TOML for nested tables of scalars and scalar lists; JSON literals are valid TOML values."""
    def key(name):
        return name if re.fullmatch(r'[A-Za-z0-9_-]+', name) else json.dumps(name)
    lines = [f'{key(name)} = {json.dumps(value)}' for name, value in table.items() if not isinstance(value, dict)]
    for name, value in table.items():
        if isinstance(value, dict):
            lines += ['', '[' + '.'.join(map(key, (*path, name))) + ']', toml_text(value, (*path, name))]
    return '\n'.join(lines)


def seed_home(home, live=None):
    """Seed a disposable CODEX_HOME; the live home is only read, never linked."""
    live = live or Path.home() / '.codex'
    kept = trimmed_config((live / 'config.toml').read_text())
    text = toml_text(kept) + '\n'
    if tomllib.loads(text) != kept:
        raise ValueError('trimmed config does not round-trip')
    (home / 'config.toml').write_text(text)
    for name in ('skills', 'plugins'):
        if (live / name).is_dir():
            subprocess.run(['cp', '-cR', str(live / name), str(home / name)], check=True, timeout=120)
    for link in [path for path in home.rglob('*') if path.is_symlink()]:
        if not link.resolve().is_relative_to(home.resolve()):
            link.unlink()  # A cloned link back into the live home could write through.


class DesktopProbe(CaseProbe):
    """The native-external matrix case through Codex's own client setup."""
    native, external = PARENT, CHILD
    parent_effort, child_effort = 'max', 'high'
    installed = False

    def __init__(self, *args):
        super().__init__(*args)
        self.facts.update(unmatched_requests=0, request_bytes=[])

    def role(self, headers):
        try:
            return super().role(headers)
        except ValueError:
            self.facts['unmatched_requests'] += 1  # Helper traffic is refused, never forwarded.
            raise

    def fetch_catalogue(self):
        """The target router's model list; no inference."""
        url = self.upstream.rsplit('/', 1)[0] + '/models?client_version=' + self.version
        with urllib.request.urlopen(urllib.request.Request(url, headers=self.auth_headers), timeout=10) as response:
            return json.loads(response.read(subscription_discovery.MAX_BYTES + 1))['models']

    def stock_client(self, home):
        """run()'s hook: seed the disposable home and keep Codex's own setup, in this tree."""
        self.catalogue_rows = {row['slug']: row for row in self.fetch_catalogue()}
        self.scope_ready = True  # That fetch already bound native membership to the target router.
        if not {self.parent, self.child} <= set(self.catalogue_rows):
            raise ValueError('router catalogue lacks the desktop case models')
        seed_home(home)
        return str(ROOT)

    def forward(self, body, headers, path='/responses', role=None):
        size = len(json.dumps(body).encode())
        request = {'turn': self.turn_index(), 'role': role, 'model': body.get('model'), 'bytes': size}
        self.facts['request_bytes'].append(request)
        if not self.installed:
            return super().forward(body, headers, path, role)
        if subscription_fallback.helper_turn(headers):
            raise ValueError('desktop case cannot forward helper traffic')
        external = body.get('model') == self.external
        defn = provider_defs.OPENROUTER if external else provider_defs.OPENAI
        reserve = sum(attempt_policy.budget(defn, provider_defs.RESPONSES).values())
        self.budget.admit(external, size, body, reserve)
        started = datetime.now(timezone.utc)
        try:
            return super().forward(body, headers, path, role)
        finally:
            rows = installed_rows(started, datetime.now(timezone.utc), [request])
            starts = [row for row in rows if row['event'] == 'request_started']
            ledgers = [row for row in rows if row['event'] == 'attempt_ledger']
            if (len(starts) != 1 or len(ledgers) != 1 or starts[0]['request_id'] != ledgers[0]['request_id']
                    or type(ledgers[0].get('sends')) is not int or not 1 <= ledgers[0]['sends'] <= reserve):
                raise ValueError('installed send ledger incomplete')
            self.router_rows.extend(rows)
            with self.budget.lock:
                self.budget.calls -= reserve - ledgers[0]['sends']

    def verify(self):
        return all(self.gates().values())

    def gates(self):
        calls = self.facts['client_calls']
        starts = [row['request_id'] for row in self.router_rows if row['event'] == 'request_started']
        ledgers = [row for row in self.router_rows if row['event'] == 'attempt_ledger']
        sends = sum(row.get('sends') or 0 for row in ledgers)
        self.facts['gates'] = gates = {
            'receipts_once': sorted(self.facts['child_receipts']) == sorted(self.markers),
            'same_child': len(self.child_agents) == 1,
            'readable_calls': {'spawn_agent', 'followup_task'} <= {call['tool'] for call in calls} and self.readable(calls),
            'no_refusals': not self.refusals() and not self.facts['rejections'],
            'complete_send_ledger': not self.installed or (
                len(starts) == len(ledgers) == len(set(starts)) == self.live_calls > 0
                and set(starts) == {row['request_id'] for row in ledgers}
                and all(type(row.get('sends')) is int and row['sends'] > 0 for row in ledgers)
                and sends == self.budget.calls),
            'within_attempt_cap': not self.installed or sends <= MAX_CALLS,
            'served_identity': all(row['model'] in ('unverified', self.routes[row['role']][0])
                                   and row['effort'] in ('unverified', self.routes[row['role']][1]) for row in self.facts['served']),
            'no_errors': not (self.errors or self.facts['tool_failures'] or self.facts['request_failures']
                              or self.facts['retry_events'] or self.facts['unmatched_requests']
                              or any(row['event'] in ('request_failed', 'request_rejected', 'turn_refused') for row in self.router_rows))}
        return gates


def installed_rows(started, ended, forwarded, logs=None):
    """The running router's content-free rows for this case's forwarded requests.

    A request_started row in the window whose model and byte size match one the
    sink forwarded names the request; its attempt and handoff rows follow by id.
    """
    logs = logs or Path.home() / '.codex/mixed-model-router/logs'
    rows = []
    for path in (logs / 'router.jsonl.1', logs / 'router.jsonl'):
        for line in path.read_text(errors='replace').splitlines() if path.exists() else ():
            try:
                row = json.loads(line)
                if started <= datetime.fromisoformat(row['ts']) <= ended:
                    rows.append(row)
            except (ValueError, KeyError, TypeError):
                continue
    sizes = {(item['model'], item['bytes']): item['turn'] for item in forwarded}
    turns = {row['request_id']: sizes[(row.get('model'), row.get('request_bytes'))] for row in rows
             if row.get('event') == 'request_started' and row.get('request_id')
             and (row.get('model'), row.get('request_bytes')) in sizes}
    return [safe_row(row, turns[row['request_id']]) for row in rows
            if row.get('request_id') in turns and row.get('event') in ROUTER_EVENTS]


def run_case(args, probe_type, case, target):
    """Run one case under one budget; print, and optionally save, its content-free record."""
    budget, probes, handlers = CaseBudget(transport.post_with_phases), [], []
    probe_type.deadline, probe_type.budget = budget.deadline, budget

    def make(*options):
        probes.append(probe_type(*options))
        if target == 'in-process':
            handlers.append(RouterRows(probes[-1]))
            LOG.addHandler(handlers[-1])
        return probes[-1]
    started, clock = datetime.now(timezone.utc), time.monotonic()
    try:
        with patch.object(transport, 'post_with_phases', budget), contextlib.ExitStack() as stack:
            for item in probe_type.patches(probes):
                stack.enter_context(item)
            result = handoffs.run(args, probe_type=make)
    except Exception as exc:  # A setup failure still leaves a record when a probe exists.
        if not probes:
            raise
        result, probes[0].facts['setup_failed'] = 1, type(exc).__name__
    finally:
        for handler in handlers:
            LOG.removeHandler(handler)
    probe, sends = probes[0], budget.calls
    if target == 'installed':
        probe.router_rows = installed_rows(started, datetime.now(timezone.utc), probe.facts['request_bytes'])
        sends = sum(row.get('sends') or 0 for row in probe.router_rows if row['event'] == 'attempt_ledger')
    return emit(probe.record(case, target, result, budget, time.monotonic() - clock, sends), args.record)


def run_legacy(args):
    """U2 on the in-process candidate; args come from probe_handoff_matrix.main."""
    handoffs.PARENT, handoffs.CHILD = args.native, LegacyProbe.external
    LegacyProbe.native, LegacyProbe.parent_effort = args.native, args.native_effort
    return run_case(args, LegacyProbe, LEGACY, 'in-process')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--installed', action='store_true', help='Target the running router, not this tree.')
    parser.add_argument('--record', type=Path, help='Also write the content-free record here.')
    args = parser.parse_args(argv)
    if not args.live:
        parser.error('requires --live; unit tests exercise the profile offline')
    handoffs.PARENT, handoffs.CHILD = PARENT, CHILD
    args.codex, args.max_live_calls, args.live_children, args.wire_mode = handoffs.codex_bin(), MAX_CALLS, True, 'lite'
    args.native_only = args.lifecycle = False
    DesktopProbe.installed = args.installed
    return run_case(args, DesktopProbe, 'desktop', 'installed' if args.installed else 'in-process')


if __name__ == '__main__':
    raise SystemExit(main())
