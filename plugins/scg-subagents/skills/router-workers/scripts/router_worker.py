#!/usr/bin/env python3
"""Run one task on a router model as a headless Claude Code worker.

The local SCG Router serves approved OpenRouter models to Claude Code, but a
Claude desktop Code session in the subscription profile talks to Anthropic
directly, so its own subagents cannot use them. This starts a separate
`claude -p` process pointed at the router, isolated from the caller's
configuration, and prints one JSON result.

    python3 router_worker.py --list
    python3 router_worker.py --model z-ai/glm-5.3-flash --effort max \
        --cwd /path/to/worktree --task-file brief.md

Standard library only. Never prints the router's per-install path token.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROUTER_HOME = Path(os.environ.get('ROUTER_HOME')
                   or Path.home() / '.codex' / 'mixed-model-router')
RUNS = Path.home() / '.cache' / 'router-workers'
TOOLS = 'Bash,Read,Edit,Write,Grep,Glob'
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
# Enough for a shell and common tools on macOS, Linux and Windows, and
# nothing that carries a login or token.
PASS_THROUGH = ('PATH', 'SHELL', 'USER', 'LOGNAME', 'LANG',
                'SYSTEMROOT', 'USERPROFILE', 'COMSPEC', 'PATHEXT')
# The worker runs in its own session, so Ctrl-C, or a parent's SIGTERM or
# SIGHUP, reaches only the runner, which must stop the worker before it exits.
STOP_SIGNALS = [getattr(signal, name) for name in ('SIGINT', 'SIGTERM', 'SIGHUP')
                if hasattr(signal, name)]  # Windows has no SIGHUP


class Interrupted(Exception):
    """The runner was told to stop while its worker ran."""


def interrupted(signum, _frame):
    raise Interrupted('interrupted by ' + signal.Signals(signum).name)


def answer_error(answer):
    """Why a final reply is not a usable result, or None when it is."""
    if answer is None:
        return 'empty_answer'
    if not isinstance(answer, str):
        return 'invalid_answer'
    text = answer.strip()
    if not text:
        return 'empty_answer'
    lowered = text.casefold().replace('\u2019', "'")
    if lowered.startswith('[tool use interrupted]'):
        return 'interrupted_answer'
    if lowered.startswith('i need to stop here'):
        return 'narration_only_answer'
    if len(text) < 240 and lowered.startswith((
            'i\'ll read', 'i\'ll continue', 'i\'ll look',
            'i will read', 'i will continue', 'i will look',
            'let me read', 'let me try reading', 'let me look',
            'let me continue')):
        return 'narration_only_answer'
    sentences = re.split(r'(?<=[.!?])\s+', lowered)
    tool_failure = re.compile(
            r'\b(read|glob|grep|file tool|file-reading tools?|tool calls?|'
            r'tool result|tools?)\b'
            r'[^.!?]{0,100}\b(returned no\s+(?:content|data|output|result|text|bytes|items)|'
            r'returned empty|'
            r'returned nothing(?:\s*(?:[.!;]|$)|\s+(?:at all|from|in|for|on|after|during)\b)|'
            r'did not return\s+(?:any\s+|the\s+)?(?:content|data|output|result|text|bytes|items)|'
            r'failed to return\s+(?:any\s+|the\s+)?(?:content|data|output|result|text|bytes|items)|'
            r'produced no\s+(?:content|data|output|result|text|bytes|items)|came back empty|'
            r'no content|no data|no output|no result|result (?:was|is|remains) missing|'
            r'failed|failure|error|could not|couldn\'t|cannot verify|'
            r'were empty|was missing)(?!\w)'
            r'|\b(?:i|we|my|our)\s+(?:could not|couldn\'t|cannot|can\'t|'
            r'failed to|unable to)\s+(?:read|glob|grep|open|load)\b')
    recovered = re.compile(
            r'\b(?:(?:i|we)\s+(?:re-?read|retry|second attempt|'
            r'subsequent (?:read|tool call))|(?:a|the|my|this)\s+'
            r'(?:retry|re-?read|second attempt)|subsequent (?:read|tool call))\b'
            r'[^.!?]{0,80}\b(?:succeeded|passed|worked|verified|confirmed|'
            r'validated|returned\s+(?:the\s+)?(?:expected|final)?\s*'
            r'(?:result|content|output|marker|contents)|'
            r'now returns|returns the expected)\b'
            r'|\b(?:i|we|my|our)\s+used (?:glob|grep)\b[^.!?]{0,40}\band\s+'
            r'(?:verified|confirmed|validated|passed)\b')
    expected_recovered = re.compile(
            r'\b(?:verified|confirmed|validated|matches|matched|passed|passes)\b'
            r'[^.!?]{0,80}\b(?:expected (?:empty|result)|empty (?:state|fixture|file)|'
            r'intentionally empty|fixture|file)\b'
            r'|\b(?:expected (?:empty|result)|empty (?:state|fixture|file)|'
            r'intentionally empty|fixture|file)\b'
            r'[^.!?]{0,80}\b(?:verified|confirmed|validated|matches|matched|'
            r'passed|passes)\b')
    recovery_negation = re.compile(
            r'\b(?:failed|did not|didn\'t|does not|doesn\'t|is not|isn\'t|'
            r'are not|aren\'t|was not|wasn\'t|were not|weren\'t|cannot|can\'t|'
            r'could not|couldn\'t|will not|won\'t|would not|wouldn\'t|'
            r'should not|shouldn\'t|has not|hasn\'t|have not|haven\'t|'
            r'had not|hadn\'t|never|not)\b')
    result_subject = (
            r'(?:this version|the (?:change|patch|task|result|file|contents?|'
            r'output|evidence|read|tool)|requested (?:file|result|contents?|'
            r'output|evidence)|file (?:result|contents?|output)|tool result|'
            r'read result)')
    result_state = (
            r'(?:unverified|unavailable|unobtainable|missing|'
            r'(?:not|isn\'t|is not|aren\'t|are not|wasn\'t|was not|weren\'t|'
            r'were not|doesn\'t|does not|can\'t|cannot|couldn\'t|could not|'
            r'never)\s+(?:be\s+)?(?:verified|confirmed|validated|available|'
            r'obtained|retrieved|retrievable|complete|readable)|'
            r'(?:cannot|can\'t|could not|couldn\'t)\s+(?:be\s+)?'
            r'(?:verify|confirmed|validate|obtain|retrieve|read))')
    result_denial = re.compile(
            rf'\b{result_subject}\b[^.!?]{{0,80}}\b{result_state}\b'
            rf'|\b{result_state}\b[^.!?]{{0,80}}\b{result_subject}\b'
            r'|^\s*(?:not\s+(?:verified|confirmed|validated|available|obtained|'
            r'retrieved|retrievable|complete|readable)|'
            r'(?:remain|remains|remained)\s+(?:unavailable|unobtainable|missing|'
            r'not\s+(?:available|obtained|retrieved|retrievable|readable))|'
            r'unverified|unavailable|unobtainable)\s*[.!?]?$')
    recovery_scope_denied = re.compile(
            r'\b(?:unrelated|different|another|separate|cache)\b')
    failed_recovery = re.compile(
            r'\b(?:retry|re-?read|second attempt|subsequent (?:read|tool call))\b'
            r'[^.!?]{0,60}\b(?:failed|did not|didn\'t|does not|doesn\'t|'
            r'could not|couldn\'t|cannot|can\'t|was not|wasn\'t|never)\b')
    prior_recovered = re.compile(
            r'\b(?:this version|final result|final suite|the fix|change)\b'
            r'[^.!?]{0,80}\b(?<!not )(?<!never )'
            r'(passes|passed|works|verified|confirmed|validated|matches|'
            r'matched|returns the expected)\b')
    empty_context = re.compile(
            r'\b(?:empty|zero-byte|zero byte|0-byte|blank)\s+'
            r'(?:file|fixture|result|output|state)|'
            r'\b(?:file|fixture|result|output|state)\s+'
            r'(?:is|was|are|were|remains?|remain)?\s*empty\b|'
            r'\bintentionally empty\b')
    verification = re.compile(
            r'\b(?:verified|confirmed|validated|matches|matched|passed|passes|'
            r'works|working)\b')
    historical_failure = re.compile(
            r'\b(?:earlier|previously|before the fix)\b')
    tool_failure_sentences = [sentence for sentence in sentences
                              if tool_failure.search(sentence)]
    if not tool_failure_sentences:
        return None
    def recovered_clause(clause):
        return (not result_denial.search(clause)
                and (recovered.search(clause) or expected_recovered.search(clause))
                and not recovery_negation.search(clause)
                and not recovery_scope_denied.search(clause))

    all_clauses = [
        clause for sentence in sentences
        for clause in re.split(r'\s*(?:;|,\s*but\b|,\s*so\b)\s*', sentence)]
    for sentence in sentences:
        clauses = re.split(r'\s*(?:;|,\s*but\b|,\s*so\b)\s*', sentence)
        denial_parts = re.split(
                r'\s*(?:;|,\s*but\b|,\s*so\b|\s+and\s+)\s*', sentence)
        if (any(result_denial.search(part) for part in denial_parts)
                and not any(recovered_clause(clause) for clause in clauses)):
            return 'tool_result_missing'
    if (empty_context.search(lowered) and verification.search(lowered)
            and not recovery_scope_denied.search(lowered)):
        return None
    def affirmative_clause(clause):
        return (recovered_clause(clause)
                or (prior_recovered.search(clause)
                    and not result_denial.search(clause)
                    and not recovery_negation.search(clause)
                    and not recovery_scope_denied.search(clause)))
    if any(failed_recovery.search(clause) and not recovered_clause(clause)
           for clause in all_clauses):
        return 'tool_result_missing'
    if (all(historical_failure.search(sentence)
            for sentence in tool_failure_sentences)
            and any(affirmative_clause(clause) for clause in all_clauses)):
        return None
    failure_indices = [index for index, sentence in enumerate(sentences)
                       if tool_failure.search(sentence)]
    for index in failure_indices:
        sentence = sentences[index]
        clauses = re.split(r'\s*(?:;|,\s*but\b|,\s*so\b)\s*', sentence)
        if any(recovered_clause(clause) for clause in clauses):
            continue
        if (index + 1 < len(sentences)
                and recovered_clause(sentences[index + 1])):
            continue
        return 'tool_result_missing'
    return None


def router():
    """Loopback base URL and the per-install path token it carries."""
    state = json.loads((ROUTER_HOME / 'mixed-router-state.json').read_text())
    return 'http://127.0.0.1:%s/%s/' % (state['port'], state['token']), state['token']


def offered(base):
    """Rows the running router lists for this install's key and policy."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base + 'v1/models', timeout=15) as response:
        return json.load(response).get('data', [])


def listing_id(slug, rows):
    """The router lists Anthropic rows by bare slug and the rest by a hash of it."""
    ids = {slug, slug.removeprefix('~'),
           'claude/scg/' + hashlib.sha256(slug.encode()).hexdigest()}
    return next((row['id'] for row in rows if row['id'] in ids), None)


def list_models(rows):
    """Offered rows with their registry slug, read from the installed release."""
    try:
        release = (ROUTER_HOME / 'current').read_text().strip()
        registry = ROUTER_HOME / 'releases' / release / 'ai_router' / 'models.json'
        slugs = {listing_id(entry['slug'], rows): entry['slug']
                 for entry in json.loads(registry.read_text())}
    except (OSError, ValueError, KeyError, TypeError):
        slugs = {}  # listing ids still print; slugs are a convenience
    return [{'model': slugs.get(row['id'], row['id']), 'name': row.get('display_name')}
            for row in rows]


def worker_env(base, model, scratch):
    """Only what the worker needs: no inherited logins, tokens or user config."""
    env = {key: os.environ[key] for key in PASS_THROUGH if key in os.environ}
    env.update({
        'HOME': str(Path.home()),
        'TMPDIR': str(scratch),
        'CLAUDE_CONFIG_DIR': str(scratch / 'config'),
        'ANTHROPIC_BASE_URL': base,
        # A placeholder, not a credential: it outranks any stored login, and
        # the router bills its own OpenRouter key for routed rows.
        'ANTHROPIC_AUTH_TOKEN': 'router-worker',
        'CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY': 'false',
        'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
    })
    for tier in ('HAIKU', 'SONNET', 'OPUS'):  # background calls stay on this row
        env['ANTHROPIC_DEFAULT_%s_MODEL' % tier] = model
    return env


def run_worker(cmd, brief, cwd, env, timeout):
    """Run to completion, or stop the worker and its shells at the deadline or
    when the runner is interrupted, returning why it stopped (None if it finished)."""
    posix = os.name == 'posix'
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, start_new_session=posix,
                            encoding='utf-8', errors='replace',
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    previous = {sig: signal.getsignal(sig) for sig in STOP_SIGNALS}
    try:
        for sig, handler in previous.items():
            if handler is not signal.SIG_IGN:  # nohup and background jobs keep ignoring it
                signal.signal(sig, interrupted)
        out, err = proc.communicate(brief, timeout=timeout)
        return out, err, None
    except (subprocess.TimeoutExpired, Interrupted) as exc:
        for sig in STOP_SIGNALS:  # a second signal must not cut the stop short
            signal.signal(sig, signal.SIG_IGN)
        stopped = str(exc) if isinstance(exc, Interrupted) else 'timed out after %ss' % timeout
        # Claude Code runs each shell command in its own process group, so a
        # group kill misses them; SIGTERM lets the client stop them first.
        # ponytail: on Windows terminate() is a hard stop and shells can outlive it.
        proc.terminate()
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            if posix:
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
            out, err = proc.communicate()
        return out, err, stopped
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def summarise(stream):
    """Answer, served models and counts from Claude Code's stream-json output."""
    served, calls, result = set(), 0, {}
    for line in stream.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'assistant':
            message = event.get('message') or {}
            if message.get('model'):
                served.add(message['model'])
            calls += sum(isinstance(part, dict) and part.get('type') == 'tool_use'
                         for part in message.get('content') or [])
        elif event.get('type') == 'result':
            result = event
    usage = result.get('usage') or {}
    input_total = sum(usage.get(key) or 0 for key in (
        'input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'))
    has_answer = 'result' in result
    quality_error = answer_error(result.get('result')) if has_answer else None
    return {'finished': has_answer and not result.get('is_error')
            and quality_error is None,
            'answer': result.get('result'), 'served': sorted(served),
            'error': (result.get('subtype') if result.get('is_error')
                      else quality_error),
            'tool_calls': calls, 'turns': result.get('num_turns'),
            'tokens': {'input': input_total, 'output': usage.get('output_tokens')}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--list', action='store_true',
                        help='print the models this router offers, then exit')
    parser.add_argument('--model', help='registry slug chosen with optimal-subagents')
    parser.add_argument('--effort', choices=EFFORTS,
                        help="the model's prescribed effort from optimal-subagents")
    brief = parser.add_mutually_exclusive_group()
    brief.add_argument('--task', help='the brief, inline')
    brief.add_argument('--task-file', type=Path, help='the brief, from a file')
    parser.add_argument('--cwd', type=Path, default=Path.cwd(),
                        help='folder the worker works in (default: here)')
    parser.add_argument('--tools', default=TOOLS,
                        help='comma-separated Claude Code tools (default: %(default)s)')
    parser.add_argument('--timeout', type=int, default=900,
                        help='seconds before the worker is stopped (default: %(default)s)')
    args = parser.parse_args(argv)
    if not args.list and not (args.model and args.effort and (args.task or args.task_file)):
        parser.error('--model, --effort and --task or --task-file are required')
    if not args.cwd.is_dir():
        parser.error('--cwd is not a folder: %s' % args.cwd)
    if not args.list and args.cwd.samefile(Path.home()):
        # Claude Code would read ~/.claude/settings.json as this folder's
        # project settings, bringing the caller's hooks and env to the worker.
        # samefile compares the folder itself, so no spelling of home slips by.
        parser.error('--cwd is the home folder; give the worker a project folder '
                     'or a scratch copy')

    token = None
    try:
        base, token = router()
        rows = offered(base)
    except (OSError, ValueError, KeyError) as exc:
        detail = str(exc).replace(token, '<router-token>') if token else str(exc)
        return report({'ok': False, 'error': 'router not reachable: ' + detail})
    if args.list:
        print(json.dumps(list_models(rows), indent=2))
        return 0
    model = listing_id(args.model, rows)
    if not model:
        return report({'ok': False, 'model': args.model,
                       'error': 'this router does not offer that model; run --list'})
    claude = os.environ.get('CLAUDE_CODE_EXECPATH') or shutil.which('claude')
    if not claude:
        return report({'ok': False, 'model': args.model,
                       'error': 'no Claude Code binary found'})

    text = args.task_file.read_text(encoding='utf-8') if args.task_file else args.task
    scratch = Path(tempfile.mkdtemp(prefix='router-worker-'))
    started = time.time()
    try:
        (scratch / 'config').mkdir()
        (scratch / 'mcp.json').write_text('{"mcpServers": {}}')
        # Parent-folder discovery would load the caller's own ~/.claude/CLAUDE.md
        # for any folder under home; the folder's own CLAUDE.md files still load.
        homes = {Path.home().as_posix(), Path.home().resolve().as_posix()}  # symlinked homes
        excludes = {'claudeMdExcludes': sorted(home + '/.claude/**' for home in homes)}
        cmd = [claude, '-p', '--model', model, '--effort', args.effort,
               '--tools', args.tools, '--allowedTools', *args.tools.split(','),
               '--permission-mode', 'dontAsk', '--strict-mcp-config',
               '--mcp-config', str(scratch / 'mcp.json'), '--setting-sources', 'project',
               '--settings', json.dumps(excludes),
               '--no-session-persistence', '--output-format', 'stream-json', '--verbose']
        out, err, stopped = run_worker(cmd, text, args.cwd,
                                       worker_env(base, model, scratch), args.timeout)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    out, err = out.replace(token, '<router-token>'), err.replace(token, '<router-token>')
    RUNS.mkdir(parents=True, exist_ok=True, mode=0o700)
    transcript = RUNS / ('%s-%s-%d.jsonl' % (time.strftime('%Y%m%d-%H%M%S'),
                                            args.model.replace('/', '_'), os.getpid()))
    transcript.write_text(out, encoding='utf-8')
    transcript.chmod(0o600)
    result = summarise(out)
    ok = result.pop('finished') and not stopped
    if stopped:
        result['error'] = stopped
    elif not ok and not result['error']:
        result['error'] = err.strip()[-500:] or 'the worker returned no result'
    # Claude Code prices unknown models as Claude, so its cost field is omitted.
    code = report({'ok': ok, 'model': args.model, 'effort': args.effort, **result,
                   'seconds': round(time.time() - started, 1),
                   'transcript': str(transcript)})
    if stopped == 'interrupted by SIGINT' and os.name == 'posix':
        # End by SIGINT, as an unhandled Ctrl-C does, or a shell loop of
        # workers would read exit 1 as a failure and start the next one.
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.raise_signal(signal.SIGINT)
    return code


def report(payload):
    print(json.dumps(payload, indent=2), flush=True)  # before any exit by signal
    return 0 if payload['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
