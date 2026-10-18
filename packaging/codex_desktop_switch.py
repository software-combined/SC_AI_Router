"""Switch the ChatGPT app (Codex) to OpenRouter models and back.

Codex desktop 26.917.51856 and later disables Send for every model once the
ChatGPT allowance runs out, but only while its provider needs OpenAI sign-in.
Switch Codex moves an attached install between the `switched` and
`switched_back` blocks of codex_switch_config, holding the installer lock
throughout, asking once, and refusing a hand-edited block before it asks.

`switched` is strict: it needs the routed model list, exactly one ChatGPT app
with its bundled CLI, a graceful quit, and a proof from Codex's own loader
(codex_config_proof); any doubt refuses before the dialog, and a failed proof
puts the old block back before the app reopens.

Switching back is the only way out of `switched`, since detach, uninstall and
rollback refuse while switched, so it depends on nothing it can lose. It runs
no proof: it only returns to the install's own block plus the provider entry.
With exactly one app found it quits and reopens it; otherwise the person
quits the app first and opens it again after. A quit that fails reopens the
app and still refuses, since the person can quit it and try again.

A marker left by a run that stopped halfway is kept when its switch was
written and needs no proof or proves, and rolled back otherwise, on the next
run. Any refusal after the quit reopens the app unchanged. The installer owns
attachment; this helper never creates or removes one. Each run appends one
line to `logs/codex-switch.log` (docs/runtime-files.md).
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _load(name):
    spec = importlib.util.spec_from_file_location(
        'router_codex_switch_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_platform = _load('claude_desktop_platform')
_blocks = _load('codex_switch_config')
_proof = _load('codex_config_proof')
_receipts = _load('codex_config')
_atomic = _load('atomic_write')
_service = _load('service')
CODEX = _platform.App('com.openai.codex', ())
MARKER = 'codex-switch-pending.json'
SWITCHED, SWITCHED_BACK = _blocks.SWITCHED, _blocks.SWITCHED_BACK
# Plain wording (AGENTS.md section 4a), naming the app as people see it.
PROMPTS = {
    SWITCHED: 'Switch the ChatGPT app (Codex) to OpenRouter models? It will restart.',
    SWITCHED_BACK: ('Switch the ChatGPT app (Codex) back to your ChatGPT subscription? '
                    'It will restart.')}
DESTINATIONS = {SWITCHED: 'OpenRouter models', SWITCHED_BACK: 'your ChatGPT subscription'}
MAC_ONLY = 'Switch Codex is available on Mac.'
BUSY = 'SCG Router is updating. Try again in a minute.'
NOTHING_TO_SWITCH = ('The ChatGPT app (Codex) already uses OpenRouter models without a '
                     'ChatGPT subscription, so there is nothing to switch.')
NOT_READY = ('SCG Router is still checking which OpenRouter models your key can use. '
             'Try again in a few minutes.')
STAYED_OPEN = ('The ChatGPT app (Codex) did not close. Quit it from the ChatGPT menu, close '
               'any Codex sessions in Terminal, then open Switch Codex again.')
NOT_PROVEN = 'The ChatGPT app (Codex) could not use the new settings, so nothing changed.'
NO_APP = ('Switch Codex could not check the ChatGPT app (Codex). Make sure one '
          'up-to-date copy is installed, then try again.')
QUIT_FIRST = ('Quit the ChatGPT app (Codex) first, then choose Continue to switch it back '
              'to your ChatGPT subscription.')
BACK_OPEN_AGAIN = ('The ChatGPT app (Codex) is switched back to your ChatGPT subscription. '
                   'Quit it if it is still open, then open it again.')
UNFINISHED = 'An earlier switch could not be finished. Contact your administrator.'
FAILED = 'The ChatGPT app (Codex) could not be switched. Try again.'


class SwitchError(Exception):
    """A message safe to show: no paths, settings, addresses or keys."""


def switch(home, *, run=subprocess.run, platform_ops=None, prove=None, ready=None, target=None):
    """Move Codex to the other variant; returns it, or None when cancelled."""
    if target not in (None, SWITCHED, SWITCHED_BACK):
        raise ValueError('Unknown Codex destination.')
    home, record = Path(home), {'to': None}
    try:
        if sys.platform not in ('darwin', 'win32', 'linux'):
            raise SwitchError(MAC_ONLY)
        # The installer's lock: an update rewrites the same config and receipt.
        with _service.install_lock(home) as held:
            if not held:
                raise SwitchError(BUSY)
            target = _switch(home, run, _platform if platform_ops is None else platform_ops,
                             _proof.prove if prove is None else prove,
                             _route_ready if ready is None else ready, record, target)
    except Exception as exc:
        _log(home, record, str(exc) if isinstance(exc, SwitchError) else FAILED)
        raise
    _log(home, record, 'done' if target else 'cancelled')
    return target


def _switch(home, run, ops, prove, ready, record, target=None):
    root = _app_root(ops, run)
    _recover(home, prove, root)
    try:
        entry = _receipts.codex_attachment(home)
        current = _blocks.current(home)
        if current is not None:
            _blocks.managed_block(entry)  # a hand edit refuses before anything is asked
    except (OSError, ValueError, SystemExit) as exc:
        raise SwitchError(_blocks.EDITED) from exc
    if current is None:
        raise SwitchError(_blocks.NOT_CONNECTED)
    if target == SWITCHED and entry.get('openai_mode') == 'none':
        return target
    if target and ((current == SWITCHED) == (target == SWITCHED)):
        return target
    target = record['to'] = target or (SWITCHED_BACK if current == SWITCHED else SWITCHED)
    if target == SWITCHED:
        if entry.get('openai_mode') == 'none':
            raise SwitchError(NOTHING_TO_SWITCH)
        if not ready(home):
            raise SwitchError(NOT_READY)
        if root is None or _proof.codex_bin(os.environ, root) is None:
            raise SwitchError(NO_APP)
    try:
        if not ops.confirm(PROMPTS[target] if root else QUIT_FIRST, sys.platform, run=run):
            return None
    except (OSError, subprocess.SubprocessError) as exc:
        raise SwitchError(FAILED) from exc
    closed = None  # the way back may go on with no app it can quit or reopen
    if root is not None:
        try:
            closed = ops.request_stop(sys.platform, run=run, app=CODEX)
        except (OSError, subprocess.SubprocessError) as exc:
            if target == SWITCHED:
                raise SwitchError(FAILED) from exc
        if closed is False:
            record['open'] = _running(root, run)  # before the reopen starts it again
            try:
                _open(ops, run)  # a refusal never leaves it closed; a running app is only shown
            except (OSError, subprocess.SubprocessError):
                pass
            raise SwitchError(STAYED_OPEN)
    try:
        _apply(home, entry, target, prove, root)
    except SwitchError as exc:
        try:
            if closed:
                _open(ops, run)
        except (OSError, subprocess.SubprocessError):
            raise SwitchError('%s Open the ChatGPT app (Codex) to continue.' % exc) from exc
        raise
    if not closed:
        _notice(ops, run, BACK_OPEN_AGAIN)
        return target
    try:
        _open(ops, run)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SwitchError('The ChatGPT app (Codex) is switched to %s. Open it to continue.'
                          % DESTINATIONS[target]) from exc
    return target


def _app_root(ops, run):
    """The ChatGPT app's bundle when exactly one is found, else None."""
    try:
        return ops.app_identity(sys.platform, run=run, app=CODEX)['root']
    except Exception:
        return None


def _files(home, entry):
    """config.toml and the receipt as they stand, or None when unreadable."""
    try:
        return tuple(path.read_text() if path.exists() else None for path in (
            Path(entry['config_path']), _receipts.receipt_path_for(home)))
    except OSError:
        return None


def _apply(home, entry, target, prove, root):
    """Write `target` with a pending marker, prove it, and undo it on any failure."""
    marker = home / MARKER
    try:
        # Carry the current pick without claiming added user settings.
        entry = _blocks.rollback_entry(entry)
        before = _files(home, entry)
        _atomic.replace_json(marker, {'to': target, 'entry': entry})
    except SystemExit as exc:
        raise SwitchError(_blocks.EDITED) from exc
    except OSError as exc:
        raise SwitchError(FAILED) from exc
    try:
        _blocks.switch(home, target)
        if target == SWITCHED and prove(root) is not True:
            raise SwitchError(NOT_PROVEN)
    except (Exception, SystemExit) as exc:
        # Undo only a write: a switch that refused first changed nothing.
        if before is None or _files(home, entry) != before:
            try:
                _blocks.restore(home, entry, target)
            except (Exception, SystemExit):
                raise SwitchError(UNFINISHED) from exc  # the marker stays for the next run
        _clear(marker)
        if isinstance(exc, SwitchError):
            raise
        raise SwitchError(_blocks.EDITED if isinstance(exc, SystemExit) else FAILED) from exc
    _clear(marker)


def _recover(home, prove, root):
    """Keep a switch that stopped after its writes when it needs no proof or proves.

    Anything else is rolled back: a way back cut short before its writes is
    offered again straight after, since it needs nothing it can lose.
    """
    marker = home / MARKER
    if not marker.exists():
        return
    try:
        pending = json.loads(marker.read_text())
        entry, target = pending['entry'], pending['to']
        written = _blocks.current(home) == target
        if not (written and (target == SWITCHED_BACK or prove(root) is True)):
            _blocks.restore(home, entry, target)
    except (Exception, SystemExit) as exc:
        raise SwitchError(UNFINISHED) from exc
    _clear(marker)


def _clear(marker):
    """A marker left behind is settled by the next run, so removal may fail."""
    try:
        marker.unlink()
    except OSError:
        pass


def _notice(ops, run, message):
    """One closing message; a dialog that cannot show changes nothing."""
    print(message)
    try:
        ops.show_message(message, sys.platform, run=run)
    except (OSError, subprocess.SubprocessError):
        pass


def _open(ops, run):
    answer = ops.open_app(sys.platform, run=run, app=CODEX)
    if getattr(answer, 'returncode', 0) != 0:
        raise OSError('the app did not open')


def _running(root, run):
    """Basenames, never paths or arguments, of what still runs from the app bundle."""
    try:
        answer = run(['/bin/ps', '-axo', 'comm='], capture_output=True, text=True, timeout=5)
        prefix = str(root).rstrip('/') + '/'  # on macOS, comm is the full executable path
        return sorted(Path(line).name for line in answer.stdout.splitlines()
                      if line.startswith(prefix))
    except Exception:
        return None


def _log(home, record, result):
    """Append this run's line to logs/codex-switch.log; a failed write changes nothing."""
    try:
        line = {'at': datetime.now().astimezone().isoformat(timespec='seconds'),
                **record, 'result': result}
        (home / 'logs').mkdir(exist_ok=True)
        with open(home / 'logs' / 'codex-switch.log', 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(line) + '\n')
    except Exception:
        pass


def _route_ready(home):
    """codex_route.ready from this release: the launcher runs the router's Python."""
    try:
        root = str(Path(__file__).resolve().parents[1])
        if root not in sys.path:
            sys.path.insert(0, root)
        from ai_router import codex_route
        return codex_route.ready(home) is True
    except Exception:
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', default=os.environ.get(
        'ROUTER_HOME', str(Path.home() / '.codex' / 'mixed-model-router')))
    parser.add_argument('--to', choices=(SWITCHED, SWITCHED_BACK))
    args = parser.parse_args(argv)
    try:
        switch(Path(args.home).expanduser(), target=args.to)
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, SwitchError) else FAILED
        print(message, file=sys.stderr)
        try:
            _platform.show_message(message, sys.platform)
        except Exception:
            pass
        return 1


if __name__ == '__main__':
    sys.exit(main())
