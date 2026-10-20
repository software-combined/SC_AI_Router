"""Run a native menu shell; keep actions asynchronous and status checks silent."""
import argparse
import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_payload import load


def _control(home, resources, action=None):
    command = [sys.executable, str(Path(__file__).with_name('desktop_control.py')),
               '--home', str(home), '--resources', str(resources)]
    if action:
        command += ['--action', action]
    result = subprocess.run(command, capture_output=True, text=True, timeout=960 if action else 15,
                            **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
    if len(result.stdout) > 65536:
        raise ValueError('Desktop response too large')
    doc = json.loads(result.stdout)
    if not isinstance(doc, dict):
        raise ValueError('Invalid desktop response')
    return doc


def fallback(home, resources):
    """The same action IDs, including profile choices, when no tray host is available."""
    with load('service').install_lock(home, session_lock() + '.window') as held:
        if held:
            return _control_window(home, resources)
    return dict(outcome='done')


def _control_window(home, resources):
    model, control = load('desktop_model'), load('desktop_control')
    removed = Path(home) / load('native_shortcuts').REMOVED
    if not removed.exists():
        try:
            facts = control.snapshot(home)
        except (Exception, SystemExit):
            facts = dict(status='Status unknown', clients=[], version='Unknown')
        details, options = model.chooser(model.menu(facts)['menu'])
        dialog = load('native_dialog')
        action = dialog.choose('\n'.join(details), options, labels=('Run action', 'Close'))
        if action is None:
            return dict(outcome='done')
        result = _control(home, resources, action)
        if result.get('outcome') == 'done' and action in (
                'router.restart', 'startup.toggle', 'codex.subscription', 'codex.openrouter',
                'claude.subscription', 'claude.openrouter', 'codex.open', 'claude.open'):
            dialog.message(dict(options)[action].rstrip('…') + ' completed.')
        return result
    return dict(outcome='done')


def _events(stream, events):
    while True:
        line = stream.readline(1025)
        if not line or len(line) > 1024:
            events.put({'closed': True})
            return
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                events.put(event, timeout=1)
        except (ValueError, queue.Full):
            pass


def session_lock():
    # UI uniqueness is per graphical session; configuration locks span sessions.
    if sys.platform == 'linux':
        session = (os.environ.get('XDG_SESSION_ID') or os.environ.get('WAYLAND_DISPLAY')
                   or os.environ.get('DISPLAY') or os.environ.get('DBUS_SESSION_BUS_ADDRESS') or 'desktop')
    else:
        session = os.environ.get('SESSIONNAME', 'console') if sys.platform == 'win32' else 'aqua'
    return '.desktop-menu-' + hashlib.sha256(session.encode()).hexdigest()[:16] + '.lock'


def mac_reopen_available(resources):
    # A retained controller can be newer than the native helper after a partial update.
    try:
        version = json.loads((resources / 'installer.json').read_text())['version']
        return tuple(map(int, version.split('.'))) >= (1, 3, 7)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def run_menu(home, resources, *, autostart=False):
    control, model = load('desktop_control'), load('desktop_model')
    removed = Path(home) / load('native_shortcuts').REMOVED
    if removed.exists():
        return 0
    helper = resources / 'control' / ('scg-router-menu.exe' if os.name == 'nt' else 'scg-router-menu')
    if not helper.is_file():
        if not autostart:
            fallback(home, resources)
        return 1
    mac_reopen = sys.platform == 'darwin' and mac_reopen_available(resources)
    if sys.platform == 'darwin' and not mac_reopen and not autostart:
        fallback(home, resources)
        return 0
    service = load('service')
    request = home / (session_lock() + '.open')
    with service.install_lock(home, session_lock()) as held:
        if not held:
            if not autostart:
                if sys.platform == 'darwin':
                    request.touch(mode=0o600)
                    deadline = time.monotonic() + 2
                    while request.exists() and time.monotonic() < deadline:
                        time.sleep(0.1)
                    try:
                        request.unlink()  # An older resident controller did not consume the request.
                    except FileNotFoundError:
                        pass
                    else:
                        fallback(home, resources)
                else:
                    fallback(home, resources)
            return 0
        try:
            if time.time() - request.stat().st_mtime > 3:
                request.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        open_menu = mac_reopen and not autostart
        events = queue.Queue(maxsize=32)
        icon = resources / 'router/packaging/assets/router-icon.png'
        try:
            shell = subprocess.Popen([str(helper), str(icon)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, bufsize=1,
                                     **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
        except OSError:
            if not autostart:
                fallback(home, resources)
            return 1
        threading.Thread(target=_events, args=(shell.stdout, events), daemon=True).start()
        facts = dict(status='Checking setup…', version='Unknown', clients=[])
        checked_update, busy, job, next_check, fallback_shown = None, None, None, 0, False
        last_doc, reload_menu, needs_fallback = None, False, False
        with ThreadPoolExecutor(max_workers=1) as worker:
            try:
                # A successful removal closes the menu, even mid-action or with a submenu open.
                while shell.poll() is None and not removed.exists():
                    if job and job.done():
                        try:
                            answer = job.result()
                            if busy:
                                checked_update = answer.get('checked_update', checked_update)
                            elif answer.get('outcome') == 'failed':
                                # Keep the last known rows so connections stay reachable.
                                facts['status'] = 'Needs attention'
                            else:
                                facts = answer
                        except (Exception, SystemExit):
                            facts['status'] = 'Needs attention'
                        job, busy, next_check = None, None, 0 if busy else time.monotonic() + 30
                    if job is None and time.monotonic() >= next_check:
                        job = worker.submit(_control, home, resources)
                    if needs_fallback and not busy:
                        needs_fallback, fallback_shown = False, True
                        job = worker.submit(fallback, home, resources)
                        busy = 'Control window open…'
                    document = model.menu(facts, busy=busy, checked_update=checked_update)
                    if mac_reopen:
                        try:
                            request.unlink()
                        except FileNotFoundError:
                            pass
                        else:
                            open_menu = True
                        if open_menu:
                            document['open_menu'] = True
                            open_menu = False
                            last_doc = None  # A second reopen request must be delivered too.
                    doc = json.dumps(document)
                    if doc != last_doc:
                        shell.stdin.write(doc + '\n')
                        shell.stdin.flush()
                        last_doc = doc
                    try:
                        name = (home / 'setup-current').read_text().strip()
                        replacement = home / 'setup' / name
                        if (name and Path(name).name == name and replacement != resources
                                and job is None and (replacement / 'control' / helper.name).is_file()):
                            load('native_payload').metadata(replacement)
                            reload_menu = True
                            break
                    except (OSError, ValueError):
                        pass
                    try:
                        event = events.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if event.get('closed'):
                        break
                    if event.get('host') is False and not autostart and not fallback_shown:
                        needs_fallback = True
                    action = event.get('action')
                    if action == 'refresh':
                        next_check = 0
                    elif action == 'menu.quit' and not busy:
                        break
                    elif action in control.ACTIONS and not busy:
                        busy = ('Opening…' if action.endswith('.open') else
                                'Switching…' if action.startswith(('codex.', 'claude.')) else
                                'Updating…' if action == 'updates.install' else 'Working…')
                        job = worker.submit(_control, home, resources, action)
            finally:
                shell.stdin.close()
                try:
                    shell.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    shell.terminate()
                    shell.wait(timeout=5)
                shell.stdout.close()
    return 75 if reload_menu else 0


def start(home, resources, *, autostart=False):
    if autostart and not load('desktop_startup').enabled(home):
        return
    helper = Path(resources) / 'control' / ('scg-router-menu.exe' if os.name == 'nt' else 'scg-router-menu')
    launcher = Path(home) / 'desktop_launch.py'
    if helper.is_file() and launcher.is_file():
        subprocess.Popen([sys.executable, str(launcher)] + (['--autostart'] if autostart else []),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt'
                            else {'start_new_session': True}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--autostart', action='store_true')
    args = parser.parse_args(argv)
    if args.autostart and not load('desktop_startup').enabled(args.home):
        return 0
    os.environ.update(load('native_setup').environment(args.resources))
    try:
        load('update_warning').offer(args.home)
    except (Exception, SystemExit):
        pass
    rc = run_menu(args.home, args.resources, autostart=args.autostart)
    if rc == 75:
        command = [sys.executable, str(args.home / 'desktop_launch.py')]
        if args.autostart:
            command.append('--autostart')
        os.execv(sys.executable, command)
    return rc


if __name__ == '__main__':
    sys.exit(main())
