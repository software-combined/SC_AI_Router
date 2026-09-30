"""Prove a switched Codex config with Codex's own loader before the app reopens.

Switch Codex writes the `switched` block while the ChatGPT app (Codex) is
closed, then starts the Codex CLI bundled in that app as a short-lived app
server on the same CODEX_HOME. The config must load, `account/read` must
report no account (that is what lets the app send without ChatGPT sign-in),
and `configRequirements/read` must carry no managed `model_provider`, which
would override the switch. A config Codex cannot read (a second root
`model_provider` in the person's own settings, say) never answers, so it
fails, as does a loader that cannot start. Switching back is never proven:
it is the only way out of `switched` and must depend on nothing it can lose.
Nothing from any answer is printed or kept, and the login file is only ever
read by Codex.

Python 3.9-safe, stdlib only and inert on import.
"""
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

# The order of tools/appserver_probe.codex_bin, copied because installed code
# never imports the checkout-run tools/ (a test pins the two), but inside the
# app Spotlight found rather than /Applications only. ChatGPT 26.924
# (codex-cli 0.158) moved the CLI into codex-cli/bin, earlier builds keep it
# one level up, and CODEX_BIN, when set, always wins.
BUNDLED = ('Contents/Resources/codex-cli/bin/codex', 'Contents/Resources/codex')


def codex_bin(env, app_root):
    """CODEX_BIN, else the first bundled CLI in the app at `app_root`, else None."""
    if env.get('CODEX_BIN'):
        return env['CODEX_BIN']
    paths = [Path(app_root) / rel for rel in BUNDLED] if app_root else []
    return next((str(path) for path in paths if path.is_file()), None)


def prove(app_root, codex_home=None, env=None, timeout=30):
    """True when Codex's loader accepts the switched config.toml, else False."""
    env = dict(os.environ if env is None else env)
    command = codex_bin(env, app_root)
    if command is None:
        return False
    # Only config.toml and Codex's own login may decide the answers: an
    # inherited API key or Codex override would change what the loader reports.
    child_env = {key: value for key, value in env.items()
                 if not key.startswith(('OPENAI_', 'CODEX_'))}
    child_env['CODEX_HOME'] = str(codex_home or Path.home() / '.codex')
    try:
        child = subprocess.Popen(
            [command, 'app-server'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=child_env)
    except OSError:
        return False
    lines = queue.Queue()
    threading.Thread(target=_pump, args=(child.stdout, lines), daemon=True).start()
    deadline = time.monotonic() + timeout
    try:
        _call(child, lines, deadline, 0, 'initialize',
              {'clientInfo': {'name': 'scg-switch-codex', 'version': '1'}})
        _send(child, {'method': 'initialized'})
        if _call(child, lines, deadline, 1, 'account/read',
                 {'refreshToken': False}).get('account') is not None:
            return False
        required = _call(child, lines, deadline, 2,
                         'configRequirements/read').get('requirements') or {}
        return not required.get('modelProvider')
    except (OSError, ValueError, AttributeError, queue.Empty):
        return False
    finally:
        _stop(child)


def _pump(stream, lines):
    for line in stream:
        lines.put(line)
    lines.put(None)


def _send(child, message):
    child.stdin.write(json.dumps(message) + '\n')
    child.stdin.flush()


def _call(child, lines, deadline, ident, method, params=None):
    """The result of one request; any error, silence or exit raises."""
    message = {'id': ident, 'method': method}
    if params is not None:
        message['params'] = params
    _send(child, message)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise queue.Empty
        line = lines.get(timeout=remaining)
        if line is None:
            raise ValueError('the loader stopped')
        try:
            reply = json.loads(line)
        except ValueError:
            continue
        if isinstance(reply, dict) and reply.get('id') == ident and 'method' not in reply:
            if 'error' in reply or not isinstance(reply.get('result'), dict):
                raise ValueError('the loader refused')
            return reply['result']


def _stop(child):
    try:
        child.stdin.close()
    except OSError:
        pass
    child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)
