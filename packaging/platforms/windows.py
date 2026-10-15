"""Windows backend (Plan 116 Stage 3). Task Scheduler lifecycle + ACL key protection.

Per-user Scheduled Tasks at logon (no admin, no stored password), updater on
a 4-hour repeat, pythonw.exe for both tasks through a home-root task
launcher that routes stdout/stderr to the router log directory, and icacls
owner-only protection verified after writing. Offline-testable: every
Windows command goes through the injected `run` seam, task XML is pure
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
_tasks_spec = _ilu.spec_from_file_location(
    'router_windows_tasks', Path(__file__).with_name('windows_tasks.py'))
_tasks = _ilu.module_from_spec(_tasks_spec)
_tasks_spec.loader.exec_module(_tasks)

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
    args = _arguments(home, script, log)
    return template.format(exe=_sax.escape(_pythonw(python), _XML_ENTITIES),
                           args=_sax.escape(args, _XML_ENTITIES),
                           user=_sax.escape(user, _XML_ENTITIES))


def _arguments(home, script, log):
    return ' '.join(_quote(a) for a in (ntpath.join(str(home), TASK_LAUNCHER), log, script))


def render_router_xml(python, home, user):
    """Router task XML; `user` is the installing account's SID."""
    if not user:
        raise SystemExit('cannot scope the logon trigger: installing user unknown')
    return _render(_ROUTER_XML, python, home, 'router_launch.py', ROUTER_LOG, user)


def render_update_xml(python, home):
    return _render(_UPDATE_XML, python, home, 'update_launch.py', UPDATE_LOG)


def render_express_xml(python, home):
    return _render(_EXPRESS_XML, python, home, 'express_launch.py', UPDATE_LOG)


def _tail(text):
    return (text or '').strip()[-500:]


def _active(task):
    return task['state'] in (2, 4) or bool(task['instances'])


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
    grantee = '*' + _winacl.current_sid(run=run)
    if path.is_dir():
        _grant(run, path, grantee + ':(OI)(CI)F', 'restrict')
        _winacl.check(path, run=run, fresh=True)
        return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _grant(run, path.parent, grantee + ':(OI)(CI)F', 'restrict')
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    _grant(run, path, grantee + ':F', 'protect')
    _winacl.check(path, run=run, fresh=True)


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
        self._sid = None

    def _call(self, cmd, **kwargs):
        """Run one console child windowless; an explicit flag wins."""
        kwargs.setdefault('creationflags', _NO_WINDOW['creationflags'])
        return self._run(cmd, **kwargs)

    def protect_secret(self, path):
        protect_file(path, run=self._call)

    def check(self, home):
        del home
        if shutil.which('powershell') is None:
            raise SystemExit('Windows PowerShell not found; '
                             'no files were changed')

    def _identity(self):
        if self._sid is None:
            self._sid = _winacl.current_sid(run=self._call)
        return self._sid

    def _task_state(self, name, home, operation='query', *, xml=None, legacy=False, pending=True):
        scripts = {ROUTER_TASK: ('router_launch.py', ROUTER_LOG),
                   UPDATE_TASK: ('update_launch.py', UPDATE_LOG),
                   EXPRESS_TASK: ('express_launch.py', UPDATE_LOG)}
        sid = self._identity()
        try:
            return _tasks.invoke(self._call, sid, name if legacy else name + '-' + sid,
                                 _arguments(home, *scripts[name]), operation, xml, pending=pending)
        except _tasks.OwnershipError:
            if not legacy or operation != 'query':
                raise
            return None

    def _running(self, name, home, *, legacy=False):
        state = self._task_state(name, home, legacy=legacy)
        if state is None:
            raise SystemExit('Windows task %s disappeared; process exit is unverified' % name)
        return _active(state)

    def _legacy(self, home):
        return {name: task for name in (ROUTER_TASK, UPDATE_TASK, EXPRESS_TASK)
                if (task := self._task_state(name, home, legacy=True)) is not None}

    def _router(self, home):
        current = self._task_state(ROUTER_TASK, home)
        legacy = self._task_state(ROUTER_TASK, home, legacy=True)
        use_legacy = bool(legacy and (not current or (_active(legacy) and not _active(current))))
        return use_legacy, legacy if use_legacy else current

    def install(self, python, home, state, release_dir, previous, *, expected_version=None):
        del previous  # the launchers resolve `current` at exec time.
        legacy = self._legacy(home)
        self._svc.install_task_launcher(home, release_dir)
        definitions = {ROUTER_TASK: render_router_xml(python, home, self._identity()),
                       UPDATE_TASK: render_update_xml(python, home)}
        if (Path(home) / 'express_launch.py').is_file():
            definitions[EXPRESS_TASK] = render_express_xml(python, home)
        # New definitions stay disabled until every registration has succeeded.
        for name, xml in definitions.items():
            old = legacy.get(name)
            pending = name == ROUTER_TASK or not old or old['enabled'] or old['pending']
            self._task_state(name, home, 'register', xml=xml, pending=pending)
        if ROUTER_TASK in legacy:
            self._task_state(ROUTER_TASK, home, 'handover', legacy=True)
            self._end_router(home, DRAIN_TIMEOUT_S, legacy=True)
        self._handover(home, state, expected_version or Path(release_dir).name)
        for name in legacy:
            task = self._task_state(name, home, 'disable', legacy=True)
            if not _active(task):
                self._task_state(name, home, 'delete', legacy=True)
        self.start_updates(home)

    def recover_pending(self, python, home, release_dir, version):
        """Complete an interrupted install before reporting this version current."""
        tasks = [self._task_state(name, home) for name in
                 (ROUTER_TASK, UPDATE_TASK, EXPRESS_TASK)]
        legacy = self._legacy(home)
        _, router = self._router(home)
        if router and not router['enabled'] and not router['pending']:
            return  # Updater setup cannot override an explicit router stop.
        if not legacy and not any(task and task['pending'] for task in tasks):
            return
        self.install(python, home, self._state(home), release_dir, None, expected_version=version)

    def _wait_stopped(self, name, timeout, home, *, legacy=False):
        deadline = time.monotonic() + timeout
        while self._running(name, home, legacy=legacy):
            if time.monotonic() >= deadline:
                return False
            self._sleep(1)
        return True

    def _drain(self, home, timeout, *, legacy=False):
        # Always ask: /shutdown is authenticated, idempotent and cheap when
        # nothing is serving, so a misread task status can never suppress
        # the drain. Returns False when the instance is still running.
        try:
            _post_shutdown(self._state(home))
        except (OSError, ValueError, KeyError):
            pass
        return self._wait_stopped(ROUTER_TASK, timeout, home, legacy=legacy)

    def _end_router(self, home, timeout, *, legacy=False):
        if not self._drain(home, timeout, legacy=legacy):
            self._stop_task(ROUTER_TASK, home, legacy=legacy)

    def _stop_task(self, name, home, *, legacy=False):
        self._task_state(name, home, 'stop', legacy=legacy)
        if not self._wait_stopped(name, 10, home, legacy=legacy):
            raise SystemExit('Windows task %s did not exit' % name)

    def _handover(self, home, state, version, *, legacy=False):
        self._task_state(ROUTER_TASK, home, 'handover', legacy=legacy)
        self._end_router(home, DRAIN_TIMEOUT_S, legacy=legacy)
        self._run_task(ROUTER_TASK, home, legacy=legacy)
        if not self._svc.wait_version(state, version):
            raise SystemExit('Windows router did not reach version %s' % version)
        self._task_state(ROUTER_TASK, home, 'complete', legacy=legacy)

    def restart(self, home):
        state = self._state(home)
        self._handover(home, state, self._svc.current_version(home), legacy=self._router(home)[0])

    def stop(self, home):
        routers = [legacy for legacy in (False, True)
                   if self._task_state(ROUTER_TASK, home, legacy=legacy) is not None]
        for legacy in routers:
            self._task_state(ROUTER_TASK, home, 'disable', legacy=legacy)
        for legacy in routers:
            self._stop_task(ROUTER_TASK, home, legacy=legacy)

    def _state(self, home):
        return json.loads((Path(home) / 'mixed-router-state.json').read_text())

    def _run_task(self, name, home, *, legacy=False):
        self._task_state(name, home, 'run', legacy=legacy)
        deadline = time.monotonic() + 10
        while True:
            state = self._task_state(name, home, legacy=legacy)
            if state and state['state'] == 4 and state['instances']:
                return
            if not state or state['state'] == 1 or time.monotonic() >= deadline:
                raise SystemExit('Windows task %s did not start (missing or disabled by policy)' % name)
            self._sleep(0.2)

    def start_updates(self, home):
        for name in (UPDATE_TASK, EXPRESS_TASK):
            state = self._task_state(name, home)
            if state and state['pending']:
                self._task_state(name, home, 'enable')

    def ensure_serving(self, home, state, version):
        if not self._running(ROUTER_TASK, home, legacy=self._router(home)[0]):
            return False
        body = self._svc.health(state, timeout=180)
        if version is not None:
            return bool(body and body.get('version') == version)
        return bool(body)

    def rollback_serving_ok(self, home, state, version):
        return bool(self.ensure_serving(home, state, version))

    def pinned_release(self, home):
        del home  # No cached in-memory command; prune freely.
        return None

    def uninstall(self, home):
        owned = [(name, legacy) for legacy in (False, True)
                 for name in (ROUTER_TASK, UPDATE_TASK, EXPRESS_TASK)
                 if self._task_state(name, home, legacy=legacy) is not None]
        for name, legacy in owned:
            self._task_state(name, home, 'disable', legacy=legacy)
            if name == ROUTER_TASK:
                self._end_router(home, UNINSTALL_DRAIN_S, legacy=legacy)
            else:
                self._stop_task(name, home, legacy=legacy)
            self._task_state(name, home, 'delete', legacy=legacy)
