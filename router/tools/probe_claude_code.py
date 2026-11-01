"""Bounded live probe: one tool round trip per model through Claude Code.

The offline suite proves the router never alters a Messages body in transit;
it cannot prove that a vendor's Anthropic-compatible endpoint accepts Claude
Code's own tool set, or that the client renders the answer it gets back. This
drives the installed `claude` binary against a running router with a synthetic
marker file, so a model that refuses the turn or returns no text fails loudly.

`--deferred` adds the leg the attached client actually runs: a synthetic MCP
server advertising 700 stub tools, tool search on, and one round trip that
must come back through the search; otherwise only built-in tools are loaded.

The unit suite stays offline. Each separate leg is capped at three client
turns and never retries a row.

`CLAUDE_BIN` overrides the client binary; the acceptance test uses it to swap
in a scripted fake. The client runs in an empty config folder, so none of the
owner's setup or login applies; it sends a synthetic bearer that
`PROBE_AUTH_TOKEN` can replace. Routed rows bill the deployment's own key.

Usage:
    python3.14 tools/probe_claude_code.py --home ~/.codex/mixed-model-router
    python3.14 tools/probe_claude_code.py --models anthropic/claude-fable-5.1
    python3.14 tools/probe_claude_code.py --candidate z-ai/glm-5.3-flash \
        --deferred
    python3.14 tools/probe_claude_code.py --output results.json --json
    python3.14 tools/probe_claude_code.py --models deepseek/deepseek-v4.1-flash-1017 \
        --read-count 2 --effort max --max-budget-usd 0.10
"""
import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
try:
    from tools.claude_probe_env import environment
    from tools.claude_probe_report import accepted as _accepted, identity as _identity, stream_report as _stream_report
except ModuleNotFoundError:
    from claude_probe_env import environment
    from claude_probe_report import accepted as _accepted, identity as _identity, stream_report as _stream_report

DEFAULT_HOME = Path.home() / '.codex' / 'mixed-model-router'
PROMPT = 'Read the file probe.txt and reply with exactly its contents, nothing else.'
MULTI_PROMPT = ('Read probe-1.txt first, then read probe-2.txt in a separate '
                'Read call after the first result arrives. Reply with exactly '
                'the two file contents separated by one space.')
# The stub MCP server and its catalogue live with the capture harness, which
# already owns the shape of a deferred Claude Code request.
ROOT = Path(__file__).resolve().parents[1]
STUB_MCP = ROOT / 'tools' / 'mcp_stub_server.py'
STUB_SERVER = 'stubtools'
STUB_TOOL = 'mcp__%s__tool_000' % STUB_SERVER
STUB_TOOLS = 700
DEFERRED_PROMPT = ('First call ToolSearch with query "select:%s", then call %s '
                   'with value "%s", then reply with exactly what it returns '
                   'and nothing else.')
TIMEOUT_S = 300
CLAUDE_BIN = os.environ.get('CLAUDE_BIN') or shutil.which('claude')


def listing(home):
    """Registry ids the running router advertises, in listing order."""
    state = json.loads((home / 'mixed-router-state.json').read_text())
    url = 'http://127.0.0.1:%s/%s/v1/models' % (state['port'], state['token'])
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=30) as response:
        return [row['id'] for row in json.load(response).get('data', [])]


def _registry_rows(home):
    try:
        release = (home / 'current').read_text().strip()
        path = home / 'releases' / release / 'ai_router' / 'models.json'
        return json.loads(path.read_text())
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _expected_model(home, model, rows=None):
    """Upstream id behind an advertised alias, or the input when unresolved."""
    for row in _registry_rows(home) if rows is None else rows:
        slug = row.get('slug')
        if not isinstance(slug, str):
            continue
        ids = {slug, slug.removeprefix('~')}
        if model in ids:
            return row.get('upstream_id') or slug
    return model


def probe(home, model, deferred=False, read_count=1, effort=None,
          max_budget_usd=None, expected_model=None):
    """One synthetic round trip; returns a result record."""
    state = json.loads((home / 'mixed-router-state.json').read_text())
    marker = 'SCGCC_' + hashlib.sha256(
        (model + ('+deferred' if deferred else '')).encode()).hexdigest()[:8].upper()
    work = Path(tempfile.mkdtemp(prefix='scg-cc-probe.'))
    try:
        markers = [marker] if read_count == 1 else [marker + '-1', marker + '-2']
        if read_count == 1:
            (work / 'probe.txt').write_text(markers[0] + '\n')
        else:
            (work / 'probe-1.txt').write_text(markers[0] + '\n')
            (work / 'probe-2.txt').write_text(markers[1] + '\n')
        env = {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:%s/%s/'
                                     % (state['port'], state['token']),
               'CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY': 'false'}
        servers = {}
        prompt, allowed = (PROMPT if read_count == 1 else MULTI_PROMPT), ['Read']
        if deferred:
            # The exact env the installer writes for an attached terminal.
            env.update({'ENABLE_TOOL_SEARCH': 'true'})
            servers = {STUB_SERVER: {
                'command': sys.executable,
                'args': [str(STUB_MCP), '--tools', str(STUB_TOOLS)]}}
            prompt = DEFERRED_PROMPT % (STUB_TOOL, STUB_TOOL, marker)
            allowed = ['Read', 'ToolSearch', STUB_TOOL]
        env = environment(work, env['ANTHROPIC_BASE_URL'],
                          os.environ.get('PROBE_AUTH_TOKEN') or 'probe-synthetic', effort, env)
        settings = work / 'settings.json'
        settings.write_text('{}')
        mcp_path = work / 'mcp.json'
        mcp_path.write_text(json.dumps({'mcpServers': servers}))
        os.chmod(settings, 0o600)
        started = time.time()
        cmd = [CLAUDE_BIN, '-p', prompt, '--model', model]
        if effort:
            cmd.extend(['--effort', effort])
        if max_budget_usd is not None:
            cmd.extend(['--max-budget-usd', str(max_budget_usd)])
        stream_output = read_count > 1 or deferred
        cmd.extend([
            '--strict-mcp-config', '--mcp-config', str(mcp_path),
            '--allowedTools', *allowed, '--settings', str(settings),
            '--output-format', 'stream-json' if stream_output else 'json']
            + (['--verbose'] if stream_output else []))
        try:
            done = subprocess.run(  # a parent's ANTHROPIC_BASE_URL outranks --settings
                cmd, env=env,
                cwd=str(work), capture_output=True, text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return {'model': model, 'leg': leg_of(deferred, read_count),
                    'effort': effort, 'max_budget_usd': max_budget_usd,
                    'pass': False,
                    'error': 'timeout',
                    'seconds': round(time.time() - started, 1)}
        report = _stream_report(done.stdout) if stream_output else _report(done.stdout)
        answer = report.get('result') or ''
        # Containment, not an exact echo: a model that reads the file and then
        # says "the contents are: <marker>" has done the job, and several rows
        # narrate their answers. An empty or refused turn still fails here.
        read_paths = sorted(set(report.get('read_paths') or ()))
        expected_model = expected_model or _expected_model(home, model)
        identity = _identity(expected_model, report)
        passed = done.returncode == 0 and _accepted(read_count, markers, report, expected_model, deferred)
        if report.get('is_error'):
            error = report.get('subtype')
        elif identity == 'mismatched':
            error = 'served_model_mismatch'
        elif done.returncode:
            error = 'client_exit'
        else:
            error = None
        return {'model': model, 'expected_model': expected_model,
                'leg': leg_of(deferred, read_count),
                'effort': effort, 'max_budget_usd': max_budget_usd, 'pass': passed,
                'turns': report.get('num_turns'),
                'calls': report.get('tool_calls') if deferred else report.get('read_calls'),
                'tool_names': report.get('tool_names'),
                'read_paths': read_paths,
                'sequential_reads': report.get('sequential_reads'),
                'tool_result_ids_match': report.get('tool_result_ids_match'),
                'served': report.get('served'),
                'served_identity': identity,
                'error': error,
                'answer': answer[:80],
                'seconds': round(time.time() - started, 1)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def leg_of(deferred, read_count=1):
    """Report label for one probe leg."""
    if deferred:
        return 'deferred'
    return 'read' if read_count == 1 else 'read2'


def _report(stdout):
    """The CLI's JSON result object; never the transcript."""
    start = stdout.find('{')
    if start < 0:
        return {}
    try:
        return json.loads(stdout[start:])
    except ValueError:
        return {}


def client_version():
    """Claude Code's version line, or None when it cannot be queried."""
    try:
        done = subprocess.run([CLAUDE_BIN, '--version'], capture_output=True,
                              text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (done.stdout or done.stderr).strip()
    return text.splitlines()[0] if text else None


def _positive_budget(value):
    """Parse a finite positive dollar cap for the live client."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError('budget must be a number') from exc
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('budget must be finite and positive')
    return number


def _summary(row):
    if row['pass']:
        return '%ss, %s turns, %s calls' % (
            row['seconds'], row.get('turns'), row.get('calls'))
    if row.get('error'):
        return '%ss, %s' % (row['seconds'], row['error'])
    return '%ss, answer %r' % (row['seconds'], row.get('answer'))


def _legs(args, home, rows=None):
    """Every probe leg, in order; the caller owns the router home."""
    results = []
    models = args.models or listing(home)
    if len(models) > args.max_rows:
        print('refusing %d rows: caps are explicit, raise --max-rows to run them'
              % len(models), file=sys.stderr)
        raise SystemExit(2)
    legs = [(model, deferred) for model in models
            for deferred in ((False, True) if args.deferred else (False,))]
    if len(legs) > args.max_legs:
        print('refusing %d legs: one model call chain each, raise --max-legs to '
              'run them' % len(legs), file=sys.stderr)
        raise SystemExit(2)
    if args.max_budget_usd is not None and len(legs) != 1:
        print('refusing %d legs: --max-budget-usd is one aggregate cap; run '
              'budgeted legs separately' % len(legs), file=sys.stderr)
        raise SystemExit(2)
    for model, deferred in legs:
        result = probe(home, model, deferred, args.read_count, args.effort,
                       args.max_budget_usd, expected_model=_expected_model(home, model, rows))
        results.append(result)
        if not args.json:
            print('%-4s %-10s %-64s %s'
                  % ('PASS' if result['pass'] else 'FAIL', result['leg'],
                     model, _summary(result)), flush=True)
    return results


def _candidate_home(slug):
    sys.path.insert(0, str(ROOT))
    from ai_router.candidate import IsolatedRouter
    return IsolatedRouter(slug, bounded=True, max_output=2048)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--home', type=Path, default=DEFAULT_HOME,
                        help='router home holding mixed-router-state.json')
    parser.add_argument('--candidate', metavar='SLUG',
                        help='boot an isolated router from this working tree '
                             'for SLUG and probe that instead of --home')
    parser.add_argument('--models', nargs='+',
                        help='ids to probe (default: every advertised row)')
    parser.add_argument('--max-rows', type=int, default=20,
                        help='hard cap on probed rows (default 20)')
    parser.add_argument('--max-legs', type=int, default=40,
                        help='hard cap on probe legs, so --deferred cannot '
                             'double the billed calls past the cap (default 40)')
    parser.add_argument('--deferred', action='store_true',
                        help='add one deferred-tool round trip per row through '
                             'a synthetic %d-tool MCP server' % STUB_TOOLS)
    parser.add_argument('--read-count', type=int, choices=(1, 2), default=1,
                        help='Read calls in the synthetic round trip '
                             '(default: 1; use 2 for multi-turn history proof)')
    parser.add_argument('--effort', choices=('low', 'medium', 'high', 'xhigh', 'max'),
                        help='reasoning effort passed to Claude Code')
    parser.add_argument('--max-budget-usd', type=_positive_budget,
                        help='hard dollar cap passed to Claude Code '
                             '(required for --read-count 2)')
    parser.add_argument('--output', type=Path, help='write results JSON here')
    parser.add_argument('--json', action='store_true', help='machine-readable')
    args = parser.parse_args(argv)

    if not CLAUDE_BIN:
        raise SystemExit('the claude binary is not on PATH')
    if args.deferred and args.read_count != 1:
        parser.error('--deferred supports one Read call; omit it for --read-count 2')
    if args.read_count > 1 and args.max_budget_usd is None:
        parser.error('--read-count 2 requires --max-budget-usd')
    if args.candidate:
        with _candidate_home(args.candidate) as scope:
            rows = json.loads((ROOT / 'ai_router' / 'models.json').read_text())
            results = _legs(args, scope.home, rows)
    else:
        results = _legs(args, args.home)

    passed = sum(1 for row in results if row['pass'])
    report = {'passed': passed, 'rows': len(results),
              'client': client_version(), 'read_count': args.read_count,
              'effort': args.effort, 'max_budget_usd': args.max_budget_usd,
              'results': results}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print('\n%d of %d legs completed their round trip' % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
