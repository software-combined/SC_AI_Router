"""First-run key window flow (Plan 139); the loopback page is the fallback.

The installer spawns this module with the setup URL and the running router
calls `open_window` from a worker thread. Either way the popup collects the
key, the subscription choice for each client this install serves (Codex,
Claude Code, or both) and the starter through `ai_router.key_dialog`,
submits them to the single-use nonce route and shows a native confirmation.
The key never enters argv, the environment, a file or a log: it travels from
the dialog tool's stdout pipe straight into the POST body. A host with no
dialog tool falls back to the loopback page, which stays the only HTML
surface.

Run manually: `python -m ai_router.key_prompt <setup-url> [--clients codex]`
or pipe the URL on stdin with `--stdin` so it never appears in `ps`.
"""
import json
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from . import key_dialog, provider_defs, setup_page, work_account


def submit(url, fields, opener=None):
    """POST the popup's choices; (status, payload) with the route's JSON."""
    if opener is None:
        opener = urllib.request.urlopen
    request = urllib.request.Request(
        url, data=urllib.parse.urlencode(fields).encode(),
        headers={'Accept': 'application/json',
                 'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with opener(request, timeout=30) as response:
            return _payload(response.status, response.read())
    except urllib.error.HTTPError as exc:
        return _payload(exc.code, exc.read())


def _payload(status, body):
    """The route's JSON, or a shaped failure for anything else it returns."""
    try:
        payload = json.loads(body or b'{}')
    except ValueError:
        payload = {}
    if not isinstance(payload, dict) or 'ok' not in payload:
        return status, {'ok': False, 'error': 'setup failed (%s)' % status}
    return status, payload


def _mode_line(mode, provider_id=None):
    label = provider_defs.label_for(provider_id or provider_defs.DEFAULT_EXTERNAL)
    return ('ChatGPT subscription and %s' % label if mode == 'subscription'
            else '%s models only' % label)


def _confirm_text(payload, which='codex', *, managed=False):
    if managed:
        action = ('Continue installation' if which == 'none'
                  else setup_page.RESTART[key_dialog.clients(which)] + ', then start a new chat')
        return 'Your work key is ready.\n\n' + action + '.'
    lines = []
    if which in ('codex', 'both'):
        lines.append('Codex: ' + _mode_line(payload.get('mode')))
    if which in ('claude', 'both'):
        lines.append('Claude Code: ' + _mode_line(payload.get('claude_mode')))
    if payload.get('starter'):
        lines.append(payload['starter'])
    return ('You are connected.\n\nKey: %s\nCredit left: %s\n%s\n\n'
            'To finish setup, %s.'
            % (payload.get('label', 'your key'),
               setup_page.remaining(payload.get('limit'), payload.get('usage')),
               '\n'.join(lines),
               setup_page.RESTART[key_dialog.clients(which)].lower()))


def _open_page(url, opener=None, label=provider_defs.label_for(provider_defs.DEFAULT_EXTERNAL)):
    """Loopback-page fallback; the URL is printed only on a TTY."""
    try:
        opened = (opener or webbrowser.open)(url) is not False
    except OSError:
        opened = False
    if sys.stdout.isatty():
        print('open %s to connect your %s key' % (url, label))
    return opened


def run_window(url, tool_path=None, platform_name=None, which=None, run=None,
               opener=None, clients='codex', post=None, provider_id=None,
               label=provider_defs.label_for(provider_defs.DEFAULT_EXTERNAL), work=False):
    """Prompt, submit, confirm. 0 stored, 2 cancelled, 3 no GUI, 1 refused."""
    if not _local_setup_url(url):
        return 1
    if platform_name is None:
        platform_name = sys.platform
    clients = key_dialog.clients(clients)
    if tool_path is None:
        tool_path = key_dialog.tool(platform_name=platform_name, which=which)
    if tool_path is None:
        _open_page(url, opener, label)
        return 3
    managed = work and (provider_id or provider_defs.DEFAULT_EXTERNAL) == provider_defs.OPENROUTER.id
    while True:
        try:
            collected = work_account.MANUAL
            if managed:
                collected = work_account.collect(tool_path, platform_name, clients, run)
                if collected is work_account.CANCELLED:
                    return 2
            if collected is work_account.MANUAL:
                managed = False
                collected = key_dialog.collect(tool_path, platform_name=platform_name,
                                               run=run, which=clients,
                                               provider_id=provider_id)
        except work_account.SignInFailed as exc:
            key_dialog.message(tool_path, str(exc), platform_name=platform_name, run=run)
            return 1
        except (OSError, subprocess.SubprocessError):
            _open_page(url, opener, label)
            return 3
        if collected is None:
            return 2
        if not collected['key']:
            key_dialog.message(tool_path, f'Paste an {label} key before saving.',
                               platform_name=platform_name, run=run)
            continue
        # Windows writes CRLF; the split above leaves the key without the
        # trailing CR, but the choices keep theirs until they are mapped.
        try:
            status, payload = submit(url, collected, opener=post)
        except (OSError, ValueError):
            key_dialog.message(tool_path,
                               'Could not reach the router; re-run the installer.',
                               platform_name=platform_name, run=run)
            return 1
        if payload.get('ok'):
            key_dialog.message(tool_path, _confirm_text(payload, clients, managed=managed),
                               platform_name=platform_name, run=run)
            return 0
        error = payload.get('error') or 'setup failed (%s)' % status
        if status == 409:
            error = 'A key is already saved on this computer. Open SCG Router and choose Check setup.'
        key_dialog.message(tool_path, error,
                           platform_name=platform_name, run=run)
        if managed or status in (404, 409):
            return 1


def open_window(url, thread=False, which=None, opener=None, platform_name=None,
                run=None, clients='codex', post=None, provider_id=None):
    """Open the popup (or the page); True when a window was started.

    `thread=True` is the router path: the popup must not hold the request
    thread, and it submits back to the same server. `opener` belongs to the
    browser fallback only; `post` is the HTTP seam, so a caller can never
    wire `webbrowser.open` into the key POST.
    """
    label = provider_defs.label_for(provider_id or provider_defs.DEFAULT_EXTERNAL)
    if platform_name is None:
        platform_name = sys.platform
    if key_dialog.tool(platform_name=platform_name, which=which) is None:
        return _open_page(url, opener, label)
    if not thread:
        return run_window(url, platform_name=platform_name, which=which, run=run,
                          opener=opener, clients=clients, post=post,
                          provider_id=provider_id, label=label, work=True) == 0
    threading.Thread(target=run_window, args=(url,),
                     kwargs=dict(platform_name=platform_name, which=which,
                                 run=run, opener=opener, clients=clients, post=post,
                                 provider_id=provider_id, label=label, work=True),
                     daemon=True).start()
    return True


def _parse(argv):
    """The setup URL plus the optional attachment set the installer knows."""
    args, which = list(argv), 'codex'
    if len(args) >= 2 and args[-2] == '--clients':
        which, args = key_dialog.clients(args[-1]), args[:-2]
    if args == ['--stdin']:
        # The installer pipes the URL here so the token never appears in `ps`.
        args = [sys.stdin.readline().strip()]
    if len(args) != 1 or not _local_setup_url(args[0]):
        return None, None
    return args[0], which


def _local_setup_url(url):
    """A work key may be submitted only to the Router's local setup route."""
    try:
        parsed = urllib.parse.urlsplit(url)
        return (parsed.scheme == 'http' and parsed.hostname == '127.0.0.1'
                and parsed.username is None and parsed.password is None
                and parsed.port is not None and 0 < parsed.port <= 65535
                and not parsed.query and not parsed.fragment
                and parsed.path.startswith('/'))
    except (ValueError, TypeError, AttributeError):
        return False


def main(argv=None):
    """CLI entry point: `python -m ai_router.key_prompt <setup-url> [--clients set]`."""
    url, which = _parse(sys.argv[1:] if argv is None else argv)
    if url is None:
        print('usage: python -m ai_router.key_prompt (<loopback setup URL> | --stdin) '
              '[--clients codex|claude|both|none]', file=sys.stderr)
        return 1
    return run_window(url, clients=which, work=True)


if __name__ == '__main__':
    sys.exit(main())
