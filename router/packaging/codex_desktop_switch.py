"""Consent, verified shutdown and rollback-safe switching of owned Codex settings.
No installation path is persisted; subscription recovery needs no CLI.
"""
import argparse
import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def _load(name):
    spec = importlib.util.spec_from_file_location(
        'router_codex_switch_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_platform = _load('claude_desktop_platform')
_transaction = _load('codex_switch_transaction')
_blocks = _transaction._blocks
_proof = _load('codex_config_proof')
_receipts = _transaction._receipts
_atomic = _transaction._atomic
_service = _load('service')
_installation = _load('windows_installation')
_dialog = _load('native_dialog')
CODEX = _platform.App('com.openai.codex', ())
MARKER = _transaction.MARKER
SWITCHED, SWITCHED_BACK = _blocks.SWITCHED, _blocks.SWITCHED_BACK
# Plain wording (AGENTS.md section 4a), naming the app as people see it.
PROMPTS = {
    SWITCHED: 'Switch the ChatGPT app (Codex) to OpenRouter models? It will restart.',
    SWITCHED_BACK: ('Switch the ChatGPT app (Codex) back to your ChatGPT subscription? '
                    'It will restart.')}
DESTINATIONS = {SWITCHED: 'OpenRouter models', SWITCHED_BACK: 'your ChatGPT subscription'}
MAC_ONLY = 'Switch Codex is available on Mac.'
BUSY = 'SCG Router is updating. Try again in a minute.'
WAITING = 'Waiting for SCG Router to finish an update. Cancel leaves Codex unchanged.'
NOTHING_TO_SWITCH = ('The ChatGPT app (Codex) already uses OpenRouter models without a '
                     'ChatGPT subscription, so there is nothing to switch.')
NOT_READY = ('SCG Router is still checking which OpenRouter models your key can use. '
             'Try again in a few minutes.')
STAYED_OPEN = ('The ChatGPT app (Codex) did not close. Quit it from the ChatGPT menu, close '
               'any Codex sessions in Terminal, then open Switch Codex again.')
NOT_PROVEN = _transaction.NOT_PROVEN
NO_APP = ('Switch Codex could not check the ChatGPT app (Codex). Make sure one '
          'up-to-date copy is installed, then try again.')
SLOW_APP = 'The ChatGPT app (Codex) took too long to check. Try Switch Codex again.'
NO_COMMAND = ('The ChatGPT app (Codex) is missing a bundled tool. Update the app, '
              'then try Switch Codex again.')
QUIT_FIRST = ('Quit the ChatGPT app (Codex) first, then choose Continue to switch it back '
              'to your ChatGPT subscription.')
BACK_OPEN_AGAIN = ('The ChatGPT app (Codex) is switched back to your ChatGPT subscription. '
                   'Quit it if it is still open, then open it again.')
UNFINISHED = _transaction.UNFINISHED
FAILED = _transaction.FAILED
CHECK_FAILED = 'Codex could not be checked. Nothing was changed. Try again.'
WINDOWS_STAYED_OPEN = 'Codex is still running. Finish active work, quit Codex, then try again.'
WINDOWS_CLOSE = 'Codex will fully close. Running tasks will stop.'
WINDOWS_RECOVER = 'Finish an earlier Codex switch? It will restart. ' + WINDOWS_CLOSE
INSTALLATION_REQUIRED = 'SCG Router needs an update or repair before Codex can switch. Open SCG Router to continue.'
SERVING_NOT_READY = 'SCG Router is not ready. Open SCG Router, then try Switch Codex again.'


SwitchError = _transaction.SwitchError


@contextlib.contextmanager
def _switch_lock(home, record):
    with contextlib.ExitStack() as lock:
        if lock.enter_context(_service.install_lock(home)):
            yield True
            return
        lock.close()
        started = time.monotonic()
        with _dialog.Progress(WAITING, **({'home': home} if sys.platform == 'win32' else {})) as progress:
            held = lock.enter_context(_service.install_lock(home, wait=60))
        record['wait_ms'] = round((time.monotonic() - started) * 1000, 1)
        if progress.cancelled:
            yield False
            return
        if not held:
            record.update(operation='install_lock', reason='timeout')
            raise SwitchError(BUSY)
        yield True


def switch(home, *, run=subprocess.run, platform_ops=None, prove=None, ready=None, target=None):
    """Move Codex to the other variant; returns it, or None when cancelled."""
    if target not in (None, SWITCHED, SWITCHED_BACK):
        raise ValueError('Unknown Codex destination.')
    home, record = Path(home), {'to': None}
    try:
        if sys.platform not in ('darwin', 'win32', 'linux'):
            raise SwitchError(MAC_ONLY)
        # The installer's lock: an update rewrites the same config and receipt.
        with _switch_lock(home, record) as held:
            if held:
                if sys.platform == 'win32' and not _installation.ready(home):
                    record.update(operation='installation', reason='component_version_mismatch')
                    raise SwitchError(INSTALLATION_REQUIRED)
                target = _switch(home, run, _platform if platform_ops is None else platform_ops,
                                 _proof.prove if prove is None else prove,
                                 _route_ready if ready is None else ready, record, target)
            else:
                target = None
    except Exception as exc:
        if 'reason' not in record and (exc.__cause__ is not None or not isinstance(exc, SwitchError)):
            record.update(_platform.error_facts(exc, 'switch'))
        _log(home, record, str(exc) if isinstance(exc, SwitchError) else FAILED)
        raise
    _log(home, record, 'done' if target else 'cancelled')
    return target


def _switch(home, run, ops, prove, ready, record, target=None):
    stayed_open = WINDOWS_STAYED_OPEN if sys.platform == 'win32' else STAYED_OPEN
    identity = _app_identity(ops, run, record)
    root = identity['root'] if identity else None
    app_exe = identity.get('exe') if identity else None
    selected = {}
    def command():
        if 'path' not in selected:
            selected['path'] = _proof.codex_bin(os.environ, root, app_exe=app_exe,
                                               run=run, record=record)
        return selected['path']
    if prove is _proof.prove:
        def prove(root):
            cli = command()
            return cli is not None and _proof.prove(root, app_exe=app_exe, command=cli)
    supplied_proof = prove
    def checked_proof(root):
        if sys.platform == 'win32' and identity and identity.get('family'):
            ops._checked_identity(sys.platform, run, CODEX, identity)
        result = _timed(record, 'proof', lambda: (sys.platform != 'win32' or _serving_current(home))
                        and supplied_proof(root))
        record['proof_ok'] = result is True
        if sys.platform == 'win32' and identity and identity.get('family'):
            ops._checked_identity(sys.platform, run, CODEX, identity)
        return result
    prove = checked_proof
    def stop(current=identity, stage='quit'):
        return _timed(record, stage, lambda: ops.request_stop(sys.platform, run=run,
            app=CODEX, identity=current, **({'allow_terminate': True, 'record': record}
                                           if sys.platform == 'win32' else {})))
    def before_restore():
        fresh = ops.app_identity(sys.platform, run=run, app=CODEX)
        if not stop(fresh, 'rollback_quit'):
            raise SwitchError(UNFINISHED)
    def reopen():
        return _timed(record, 'reopen', lambda: _open(ops, run, identity))
    if sys.platform == 'win32' and root is None:
        raise SwitchError(SLOW_APP if record.get('reason') == 'timeout' else NO_APP)
    if sys.platform == 'win32' and (home / MARKER).exists():
        if not _timed(record, 'confirmation', lambda: ops.confirm(
                WINDOWS_RECOVER, sys.platform, run=run, home=home)):
            return None
        closed = False
        try:
            if not stop():
                raise SwitchError(stayed_open)
            closed = True
            _recover(home, prove, root, reopen=reopen, before_restore=before_restore)
        except (OSError, subprocess.SubprocessError, SwitchError) as exc:
            try:
                if closed:
                    _open(ops, run, identity, fresh=True)
            except (OSError, subprocess.SubprocessError):
                raise SwitchError(FAILED + ' Open the ChatGPT app (Codex) to continue.') from exc
            raise
        record['to'] = _blocks.current(home)
        if target is None:
            return record['to']
        if (home / MARKER).exists():
            raise SwitchError(UNFINISHED)
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
        if sys.platform == 'win32' and not _serving_current(home):
            record.update(operation='installation', reason='serving_version_unavailable')
            raise SwitchError(SERVING_NOT_READY)
        if not ready(home):
            raise SwitchError(NOT_READY)
        if root is None:
            record.setdefault('reason', 'app_unavailable')
            raise SwitchError(SLOW_APP if record['reason'] == 'timeout' else NO_APP)
        if command() is None:
            record['reason'] = 'bundled_command_missing'
            raise SwitchError(NO_COMMAND)
    try:
        prompt = PROMPTS[target] if root else QUIT_FIRST
        if sys.platform == 'win32':
            prompt += '\n\n' + WINDOWS_CLOSE
        if not _timed(record, 'confirmation', lambda: ops.confirm(prompt, sys.platform,
                run=run, **({'home': home} if sys.platform == 'win32' else {}))):
            return None
    except (OSError, subprocess.SubprocessError) as exc:
        raise SwitchError(FAILED) from exc
    closed = None  # the way back may go on with no app it can quit or reopen
    if root is not None:
        try:
            closed = stop()
        except (OSError, subprocess.SubprocessError) as exc:
            if target == SWITCHED or sys.platform == 'win32':
                record.update(_platform.error_facts(exc, 'request_stop'))
                message = stayed_open if record.get('reason') == 'still_running' else (
                    CHECK_FAILED if sys.platform == 'win32' else FAILED)
                if getattr(exc, 'reopen_failed', False) is True:
                    message += ' Open the ChatGPT app (Codex) to continue.'
                raise SwitchError(message) from exc
        if closed is False:
            record.setdefault('reason', 'close_not_confirmed')
            record['open'] = _running(root, run)  # before the reopen starts it again
            try:
                _open(ops, run, identity)  # A refusal never leaves the app closed.
            except (OSError, subprocess.SubprocessError):
                pass
            raise SwitchError(stayed_open)
    try:
        _apply(home, entry, target, prove, root,
               reopen=reopen if sys.platform == 'win32' and closed else None,
               before_restore=before_restore if sys.platform == 'win32' and closed else None)
    except SwitchError as exc:
        try:
            if closed:
                _open(ops, run, identity, fresh=sys.platform == 'win32')
        except (OSError, subprocess.SubprocessError):
            raise SwitchError('%s Open the ChatGPT app (Codex) to continue.' % exc) from exc
        raise
    if not closed:
        _notice(ops, run, BACK_OPEN_AGAIN)
        return target
    if sys.platform == 'win32':
        return target  # The verified reopen happened inside the rollback boundary.
    try:
        _open(ops, run, identity)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SwitchError('The ChatGPT app (Codex) is switched to %s. Open it to continue.'
                          % DESTINATIONS[target]) from exc
    return target


def _app_identity(ops, run, record):
    """Keep the verified executable together with its package root."""
    try:
        return _timed(record, 'identity', lambda: ops.app_identity(sys.platform, run=run, app=CODEX))
    except Exception as exc:
        record.update(_platform.error_facts(exc, 'app_identity'))
        return None


_files, _apply, _recover, _clear = (
    _transaction._files, _transaction._apply, _transaction._recover, _transaction._clear)


def _notice(ops, run, message):
    """One closing message; a dialog that cannot show changes nothing."""
    print(message)
    try:
        ops.show_message(message, sys.platform, run=run)
    except (OSError, subprocess.SubprocessError):
        pass


def _open(ops, run, identity, *, fresh=False):
    if fresh:
        identity = ops.app_identity(sys.platform, run=run, app=CODEX)
    answer = ops.open_app(sys.platform, run=run, app=CODEX, identity=identity)
    if getattr(answer, 'returncode', 0) != 0:
        raise OSError('the app did not open')


_running = _platform.running_names


_timed = _platform.timed


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


def _serving_current(home):
    try:
        state = _service._state.read(_service._state.path(home))
        body = _service.health(state, timeout=2) if isinstance(state, dict) else None
        return bool(body and body.get('version') == _service.current_version(home))
    except (OSError, ValueError, KeyError, TypeError):
        return False


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
        if getattr(exc, 'reopen_failed', False) is True:
            message += ' Open the ChatGPT app (Codex) to continue.'
        print(message, file=sys.stderr)
        try:
            _platform.show_message(message, sys.platform,
                                   **({'home': Path(args.home).expanduser()} if sys.platform == 'win32' else {}))
        except Exception:
            pass
        return 1

if __name__ == '__main__':
    sys.exit(main())
