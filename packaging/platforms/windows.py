"""Windows backend (Plan 116 Stage 3). Task Scheduler lifecycle + ACL key protection.

Per-user Scheduled Tasks at logon (no admin, no stored password), updater on
a 4-hour repeat, pythonw.exe for both tasks through a home-root task
launcher that routes stdout/stderr to the router log directory, and icacls
owner-only protection verified after writing. Offline-testable: every
schtasks call goes through the injected `run` seam, task XML is pure
rendering over (python, home, user), and the shutdown request goes through
the patchable `_post_shutdown` seam. Wired in select(); staff rollout stays
gated on real-machine acceptance.
"""
import os
import json
import ntpath
import shutil
import subprocess
import time
import urllib.request
import xml.sax.saxutils as _sax
from pathlib import Path

import importlib.util as _ilu
_winacl_spec = _ilu.spec_from_file_location(
    'router_winacl', Path(__file__).resolve().parents[2] / 'ai_router' / 'winacl.py')
_winacl = _ilu.module_from_spec(_winacl_spec)
_winacl_spec.loader.exec_module(_winacl)

_XML_ENTITIES = {'"': '&quot;', "'": '&apos;'}

ROUTER_TASK = 'CodexMixedModelRouter'
UPDATE_TASK = ROUTER_TASK + 'Update'
EXPRESS_TASK = UPDATE_TASK + 'Express'
TASK_LAUNCHER = 'task_launch.py'  # written beside router_launch.py on install
ROUTER_LOG = 'launchd.log'   # same supervisor log names as the other platforms
UPDATE_LOG = 'update.log'
# Covers the router's 120-second request drain plus start-up slack; the
# launchd ExitTimeOut and systemd TimeoutStopSec use 150 for the same drain.
DRAIN_TIMEOUT_S = 180
# Uninstall is an explicit operator action: it still asks the router to drain
# first, but bounds the wait so removal never hangs on a stuck request.
UNINSTALL_DRAIN_S = 30
# Console rule: schtasks, icacls and whoami are console programs. Spawned
# from a console-less parent (the pythonw updater running this installer)
# each would flash a console window on the interactive desktop.
_NO_WINDOW = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}

# Plan 112 slice 4: logon trigger plus a one-minute repeated recovery
# trigger (duplicate launches ignored), 4-hour updater, IgnoreNew,
# unlimited router execution time (PT0S), battery settings that do not
# stop working sessions, interactive-token least-privilege execution.
_TASK_HEAD = (
    '<?xml version="1.0" encoding="UTF-16"?>\n'
    '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
    '  <RegistrationInfo><Author>codex-router-installer</Author></RegistrationInfo>\n'
    '  <Triggers>\n')

# Scoped to the installing user: an unscoped logon trigger fires for any
# account, which only an elevated principal may register ("Access is
# denied" for a standard user, verified Windows 11 2026-09-10).
_LOGON_TRIGGER = ('    <LogonTrigger><UserId>{user}</UserId>'
                  '<Enabled>true</Enabled></LogonTrigger>\n')


def _repeat_trigger(interval):
    # The one Task Scheduler idiom for "every N minutes, indefinitely": a
    # daily calendar trigger whose repetition lasts the whole day. A bare
    # TimeTrigger without StartBoundary is refused at registration
    # ("(6,118):StartBoundary"), verified on Windows 11 2026-09-10.
    return ('    <CalendarTrigger><Repetition><Interval>%s</Interval>'
            '<Duration>P1D</Duration></Repetition>'
            '<StartBoundary>2000-01-01T00:00:00</StartBoundary>'
            '<Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval>'
            '</ScheduleByDay></CalendarTrigger>\n' % interval)


_TASK_MID = (
    '  </Triggers>\n'
    '  <Principals><Principal id="Author">'
    '<LogonType>InteractiveToken</LogonType>'
    '<RunLevel>LeastPrivilege</RunLevel></Principal></Principals>\n'
    '  <Settings>'
    '<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>'
    '<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>'
    '<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>')

_TASK_TAIL = (
    '</Settings>\n'
    '  <Actions Context="Author"><Exec>'
    '<Command>{exe}</Command><Arguments>{args}</Arguments>'
    '</Exec></Actions>\n'
    '</Task>\n')

# One shell; only the triggers and the execution time limit differ, so a
# policy change cannot land in one task and silently miss the other.
_ROUTER_XML = (_TASK_HEAD + _LOGON_TRIGGER + _repeat_trigger('PT1M') + _TASK_MID
               + '<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>'
               + _TASK_TAIL)
_UPDATE_XML = (_TASK_HEAD + _repeat_trigger('PT4H') + _TASK_MID
               + '<ExecutionTimeLimit>PT30M</ExecutionTimeLimit>'
               + _TASK_TAIL)
_EXPRESS_XML = _UPDATE_XML.replace('PT4H', 'PT1M')

def _quote(arg):
    # schtasks /xml carries no shell, but the Task Scheduler command line
    # does: quote any argument containing a space or quote.
    if not arg or any(c in arg for c in ' \t"'):
        return '"' + arg.replace('"', '""') + '"'
    return arg


def _pythonw(python):
    lower = python.lower()
    if lower.endswith('python.exe'):
        return python[:-10] + 'pythonw.exe'
    return python


def _render(template, python, home, script, log, user=''):
    # ntpath, not pathlib: the XML must render the same Windows path on a
    # POSIX host (tests, release tooling) as on the machine that registers it.
    launcher = ntpath.join(str(home), TASK_LAUNCHER)
    args = ' '.join(_quote(a) for a in (launcher, log, script))
    return template.format(exe=_sax.escape(_pythonw(python), _XML_ENTITIES),
                           args=_sax.escape(args, _XML_ENTITIES),
                           user=_sax.escape(user, _XML_ENTITIES))


def render_router_xml(python, home, user):
    """Router task XML; `user` is the installing account as whoami names it."""
    if not user:
        raise SystemExit('cannot scope the logon trigger: installing user unknown')
    return _render(_ROUTER_XML, python, home, 'router_launch.py', ROUTER_LOG, user)


def render_update_xml(python, home):
    return _render(_UPDATE_XML, python, home, 'update_launch.py', UPDATE_LOG)


def render_express_xml(python, home):
    return _render(_EXPRESS_XML, python, home, 'express_launch.py', UPDATE_LOG)


def _tail(text):
    return (text or '').strip()[-500:]


def _grantee(run):
    """Installing account for icacls grants, qualified as whoami reports it.

    The qualified name is what icacls prints back, so the post-write check
    compares like with like; %USERNAME% is the fallback, never a literal.
    """
    whoami = run(['whoami'], capture_output=True, text=True)
    owner = (whoami.stdout or '').strip()
    if owner:
        return owner
    expanded = os.path.expandvars('%USERNAME%')
    if expanded and expanded != '%USERNAME%':
        return expanded
    raise SystemExit('cannot determine the installing user for key protection')


def _grant(run, path, grantee, verb):
    result = run(['icacls', str(path), '/inheritance:r', '/grant:r', grantee],
                 capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit('cannot %s %s: %s' % (verb, path, _tail(result.stderr)))


def protect_file(path, run):
    """Restrict path to the installing user via icacls; verify afterwards.

    Given the router home itself (an existing directory), hardens it in
    place with an inheritable owner-only grant so every file created inside
    afterwards is born owner-only: call this before minting any token or key.
    Given a file, hardens its parent the same way first, creates the file
    if missing, grants it explicitly, then verifies. Raises SystemExit
    naming the exact failure; never silently leaves an exposed secret.
    """
    path = Path(path)
    grantee = _grantee(run)
    if path.is_dir():
        _grant(run, path, grantee + ':(OI)(CI)F', 'restrict')
        _winacl.check(path, run=run)
        return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _grant(run, path.parent, grantee + ':(OI)(CI)F', 'restrict')
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    _grant(run, path, grantee + ':F', 'protect')
    _winacl.check(path, run=run)


def _post_shutdown(state):
    """Authenticated graceful drain; True when the router accepted it."""
    url = 'http://127.0.0.1:%s/%s/shutdown' % (state['port'], state['token'])
    req = urllib.request.Request(url, data=b'{}', method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


class Backend:
    name = 'windows'

    def __init__(self, svc, run):
        self._svc = svc
        self._run = run
        self._sleep = time.sleep

    def _call(self, cmd, **kwargs):
        """Run one console child windowless; an explicit flag wins."""
        kwargs.setdefault('creationflags', _NO_WINDOW['creationflags'])
        return self._run(cmd, **kwargs)

    def protect_secret(self, path):
        protect_file(path, run=self._call)

    def check(self, home):
        del home
        if shutil.which('schtasks') is None:
            raise SystemExit('Task Scheduler command (schtasks) not found; '
                             'no files were changed')

    def _register(self, name, xml, home):
        # Written beside the router log directory, never into a prunable
        # release path; the XML is a registration vehicle, not a secret.
        # Re-registering a running task keeps its instance alive (verified
        # 2026-09-10), so the updater may safely refresh its own definition.
        xml_path = Path(home) / 'logs' / (name + '.task.xml')
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        xml_path.write_text(xml, encoding='utf-16')
        result = self._call(['schtasks', '/create', '/tn', name,
                             '/xml', str(xml_path), '/f'],
                            capture_output=True, text=True)
        if result.returncode != 0:
            # `/f` overwrites a task this caller already owns, but it CANNOT
            # overwrite one registered under a different principal: an install
            # first made under a local account (UserId = a local SID) is
            # "Access is denied" to the same human's domain token
            # (ACTIVATE\user), and vice versa. Deleting the stale task clears
            # the owner, so a plain re-create then lands under the current
            # principal. Verified on Windows 11 2026-09-16 (local->domain
            # account switch). Only retried on failure, so a first, clean
            # install keeps the running instance alive as before.
            self._call(['schtasks', '/delete', '/tn', name, '/f'],
                       capture_output=True, text=True)
            result = self._call(['schtasks', '/create', '/tn', name,
                                 '/xml', str(xml_path), '/f'],
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit('Windows task registration failed for %s: %s'
                             % (name, _tail(result.stderr or result.stdout)))

    def _task_state(self, name):
        # schtasks /query is the registration-and-running readback: a task
        # silently disabled by group policy reports here instead of being
        # assumed healthy.
        result = self._call(['schtasks', '/query', '/tn', name,
                             '/fo', 'list', '/v'],
                            capture_output=True, text=True)
        if result.returncode != 0:
            return None
        state = {}
        for line in (result.stdout or '').splitlines():
            if ':' in line:
                key, _, value = line.partition(':')
                state[key.strip().lower()] = value.strip()
        return state

    def _running(self, name, home):
        # Status is localised: an unreadable line falls back to /health.
        # The drain never depends on this alone (_drain posts first).
        state = self._task_state(name)
        if state is None:
            return False
        if 'running' in state.get('status', '').lower():
            return True
        try:
            probe = self._svc.health(self._state(home), timeout=2)
        except (OSError, ValueError, KeyError):
            return False
        return probe is not None

    def _registered_and_running(self, name):
        state = self._task_state(name)
        if state is None:
            raise SystemExit('Windows task %s is not registered after creation: '
                             'check group policy before retrying' % name)
        status = state.get('status', '').lower()
        if 'disabled' in status:
            raise SystemExit('Windows task %s is registered but disabled by policy '
                             '(status %r): enable the task or grant logon-task '
                             'creation before retrying' % (name, status))
        return state

    def install(self, python, home, state, release_dir, previous):
        del previous  # the launchers resolve `current` at exec time.
        # Task Scheduler captures no stdout, and an InteractiveToken console
        # task shows its window for its whole run, so both tasks run pythonw
        # through this packaged launcher: it rotates the supervisor log,
        # appends stdout/stderr to it, then runs the home launcher named on
        # the command line (argv: LOG SCRIPT).
        self._svc.install_task_launcher(home, release_dir)
        self._register(ROUTER_TASK,
                       render_router_xml(python, home, _grantee(self._call)), home)
        self._register(UPDATE_TASK, render_update_xml(python, home), home)
        if (Path(home) / 'express_launch.py').is_file():
            self._register(EXPRESS_TASK, render_express_xml(python, home), home)
        self._handover(home)

    def _wait_stopped(self, name, timeout, home):
        deadline = time.monotonic() + timeout
        while self._running(name, home):
            if time.monotonic() >= deadline:
                return False
            self._sleep(1)
        return True

    def _drain(self, home, timeout):
        # Always ask: /shutdown is authenticated, idempotent and cheap when
        # nothing is serving, so a misread task status can never suppress
        # the drain. Returns False when the instance is still running.
        try:
            _post_shutdown(self._state(home))
        except (OSError, ValueError, KeyError):
            pass
        return self._wait_stopped(ROUTER_TASK, timeout, home)

    def _handover(self, home):
        # The task supervises one instance (IgnoreNew), so a running router
        # must leave before /run can start the new pointer: drain it, wait
        # for the instance to end, then run. Never taskkill /F a serving
        # router; /end is reserved for a process still alive after the whole
        # drain deadline, which only a hung router reaches.
        if not self._drain(home, DRAIN_TIMEOUT_S):
            self._call(['schtasks', '/end', '/tn', ROUTER_TASK], capture_output=True)
            self._wait_stopped(ROUTER_TASK, 10, home)
        self._run_task(ROUTER_TASK)

    def restart(self, home):
        self._handover(home)

    def stop(self, home):
        result = self._call(['schtasks', '/end', '/tn', ROUTER_TASK],
                            capture_output=True, text=True)
        if result.returncode == 0:
            return
        if self._task_state(ROUTER_TASK) is None:
            return  # never registered (failed first install): nothing to stop
        raise SystemExit('Windows task failed to stop %s: %s'
                         % (ROUTER_TASK, _tail(result.stderr)))

    def _state(self, home):
        return json.loads((Path(home) / 'mixed-router-state.json').read_text())

    def _run_task(self, name):
        self._call(['schtasks', '/run', '/tn', name], capture_output=True)
        self._registered_and_running(name)

    def start_updates(self, home):
        del home  # The updater task runs on its own 4-hour trigger.
        return None

    def ensure_serving(self, home, state, version):
        # The installer's last act on every path: a pointer swap plus task
        # control cannot recover a task that is not registered, so verify
        # registration before trusting /health.
        self._registered_and_running(ROUTER_TASK)
        body = self._svc.health(state, timeout=180)
        if version is not None:
            return bool(body and body.get('version') == version)
        return bool(body)

    def rollback_serving_ok(self, home, state, version):
        # The launchers resolve `current` at exec time, so the restored
        # release is live once the task runs; verify it serves rather than
        # assuming so.
        self._call(['schtasks', '/run', '/tn', ROUTER_TASK], capture_output=True)
        return bool(self.ensure_serving(home, state, version))

    def pinned_release(self, home):
        del home  # No cached in-memory command; prune freely.
        return None

    def uninstall(self, home):
        # Deleting a task leaves its running instance alive (verified
        # 2026-09-10), so drain and end the router before either
        # definition goes; otherwise the old router serves until sign-out.
        self._drain(home, UNINSTALL_DRAIN_S)
        tasks = [ROUTER_TASK, UPDATE_TASK]
        if self._task_state(EXPRESS_TASK) is not None:
            tasks.append(EXPRESS_TASK)
        for task in tasks:
            self._call(['schtasks', '/end', '/tn', task], capture_output=True)
            result = self._call(['schtasks', '/delete', '/tn', task, '/f'],
                                capture_output=True)
            if result.returncode != 0:
                raise SystemExit('Windows task survived uninstall: %s' % task)
