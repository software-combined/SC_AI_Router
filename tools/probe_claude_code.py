"""Bounded live probe: one Read-tool round trip per model through Claude Code.

The offline suite proves the router never alters a Messages body in transit;
it cannot prove that a vendor's Anthropic-compatible endpoint accepts Claude
Code's own tool set, or that the client renders the answer it gets back. This
drives the installed `claude` binary against a running router with a synthetic
marker file, so a model that refuses the turn or returns no text fails loudly.

The unit suite stays offline. This is invoked separately, makes one model call
per row plus its tool round trip, and never retries a row.

`CLAUDE_BIN` overrides the client binary; the acceptance test uses it to swap
in a scripted fake.

Usage:
    python3.14 tools/probe_claude_code.py --home ~/.codex/mixed-model-router
    python3.14 tools/probe_claude_code.py --models anthropic/claude-fable-5.1
    python3.14 tools/probe_claude_code.py --output results.json --json
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

DEFAULT_HOME = Path.home() / '.codex' / 'mixed-model-router'
PROMPT = 'Read the file probe.txt and reply with exactly its contents, nothing else.'
TIMEOUT_S = 300
CLAUDE_BIN = os.environ.get('CLAUDE_BIN') or shutil.which('claude')


def listing(home):
    """Registry ids the running router advertises, in listing order."""
    state = json.loads((home / 'mixed-router-state.json').read_text())
    url = 'http://127.0.0.1:%s/%s/v1/models' % (state['port'], state['token'])
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=30) as response:
        return [row['id'] for row in json.load(response).get('data', [])]


def probe(home, model):
    """One synthetic Read round trip; returns a result record."""
    state = json.loads((home / 'mixed-router-state.json').read_text())
    marker = 'SCGCC_' + hashlib.sha256(model.encode()).hexdigest()[:8].upper()
    work = Path(tempfile.mkdtemp(prefix='scg-cc-probe.'))
    try:
        (work / 'probe.txt').write_text(marker + '\n')
        settings = work / 'settings.json'
        settings.write_text(json.dumps({'env': {
            'ANTHROPIC_BASE_URL': 'http://127.0.0.1:%s/%s/'
                                  % (state['port'], state['token']),
            'CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY': 'false'}}))
        os.chmod(settings, 0o600)
        started = time.time()
        try:
            done = subprocess.run(
                [CLAUDE_BIN, '-p', PROMPT, '--model', model,
                 '--strict-mcp-config', '--mcp-config', '{"mcpServers": {}}',
                 '--allowedTools', 'Read', '--settings', str(settings),
                 '--output-format', 'json'],
                cwd=str(work), capture_output=True, text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return {'model': model, 'pass': False, 'error': 'timeout',
                    'seconds': round(time.time() - started, 1)}
        report = _report(done.stdout)
        answer = report.get('result') or ''
        # Containment, not an exact echo: a model that reads the file and then
        # says "the contents are: <marker>" has done the job, and several rows
        # narrate their answers. An empty or refused turn still fails here.
        return {'model': model, 'pass': marker in answer,
                'turns': report.get('num_turns'),
                'error': report.get('subtype') if report.get('is_error') else None,
                'answer': answer[:80],
                'seconds': round(time.time() - started, 1)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _report(stdout):
    """The CLI's JSON result object; never the transcript."""
    start = stdout.find('{')
    if start < 0:
        return {}
    try:
        return json.loads(stdout[start:])
    except ValueError:
        return {}


def _summary(row):
    if row['pass']:
        return '%ss, %s turns' % (row['seconds'], row.get('turns'))
    if row.get('error'):
        return '%ss, %s' % (row['seconds'], row['error'])
    return '%ss, answer %r' % (row['seconds'], row.get('answer'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--home', type=Path, default=DEFAULT_HOME,
                        help='router home holding mixed-router-state.json')
    parser.add_argument('--models', nargs='+',
                        help='ids to probe (default: every advertised row)')
    parser.add_argument('--max-rows', type=int, default=20,
                        help='hard cap on probed rows (default 20)')
    parser.add_argument('--output', type=Path, help='write results JSON here')
    parser.add_argument('--json', action='store_true', help='machine-readable')
    args = parser.parse_args(argv)

    if not CLAUDE_BIN:
        raise SystemExit('the claude binary is not on PATH')
    models = args.models or listing(args.home)
    if len(models) > args.max_rows:
        print('refusing %d rows: caps are explicit, raise --max-rows to run them'
              % len(models), file=sys.stderr)
        return 2

    results = []
    for model in models:
        results.append(probe(args.home, model))
        if not args.json:
            row = results[-1]
            print('%-4s %-72s %s' % ('PASS' if row['pass'] else 'FAIL',
                                     model, _summary(row)), flush=True)

    passed = sum(1 for row in results if row['pass'])
    report = {'passed': passed, 'rows': len(results), 'results': results}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print('\n%d of %d rows completed a Read round trip' % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
