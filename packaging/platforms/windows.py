"""Windows backend (Plan 057 Stage 3). Task Scheduler lifecycle + ACL key protection.

Per-user Scheduled Tasks at logon (no admin, no stored password), updater on
a 15-minute repeat, pythonw.exe router with python.exe updater, and icacls
owner-only key protection verified after writing. Offline-testable: every
schtasks call goes through the injected `run` seam, and task XML is pure
rendering over (python, home). Wired in select(); staff rollout stays
gated on real-machine acceptance.
"""
import os
import json
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

# Plan 049 slice 4: logon trigger plus a one-minute repeated recovery
# trigger (duplicate launches ignored), 15-minute updater, IgnoreNew,
# unlimited router execution time (PT0S), battery settings that do not
# stop working sessions, interactive-token least-privilege execution.
_TASK_HEAD = (
    '<?xml version="1.0" encoding="UTF-16"?>\n'
    '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
    '  <RegistrationInfo><Author>codex-router-installer</Author></RegistrationInfo>\n'
    '  <Triggers>\n')

_ROUTER_TRIGGERS = (
    '    <LogonTrigger><Enabled>true</Enabled></LogonTrigger>\n'
    '    <TimeTrigger><Repetition><Interval>PT1M</Interval>'
'<Duration>P1D</Duration></Repetition>'
'<Enabled>true</Enabled></TimeTrigger>\n')

_UPDATE_TRIGGERS = (
    '    <CalendarTrigger><Repetition><Interval>PT15M</Interval>'
'<Duration>P1D</Duration></Repetition>'
'<StartBoundary>2000-01-01T00:00:00</StartBoundary>'
'<Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval>'
'</ScheduleByDay></CalendarTrigger>\n')

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
_ROUTER_XML = (_TASK_HEAD + _ROUTER_TRIGGERS + _TASK_MID
               + '<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>'
               + _TASK_TAIL)
_UPDATE_XML = (_TASK_HEAD + _UPDATE_TRIGGERS + _TASK_MID
               + '<ExecutionTimeLimit>PT30M</ExecutionTimeLimit>'
               + _TASK_TAIL)


def _quote(arg):
    # schtasks /xml carries no shell, but the Task Scheduler command line
    # does: quote any argument containing a space or quote.
    if not arg or any(c in arg for c in ' \t"'):
        return '"' + arg.replace('"', '""') + '"'
    return arg


def _router_exe(python):
    # Console window rule (Plan 057): pythonw.exe for the router so no
    # console appears for its lifetime; python.exe for the updater so its
    # output still reaches the task log.
    lower = python.lower()
    if lower.endswith('python.exe'):
        return python[:-10] + 'pythonw.exe'
    return python


def _render(template, exe, home, script):
    args = '%s %s' % (_quote(str(Path(home) / script)),
                      _quote('--home=%s' % home))
    return template.format(exe=_sax.escape(exe, _XML_ENTITIES),
                           args=_sax.escape(args, _XML_ENTITIES))


def render_router_xml(python, home):
    return _render(_ROUTER_XML, _router_exe(python), home, 'router_launch.py')


def render_update_xml(python, home):
    return _render(_UPDATE_XML, python, home, 'update_launch.py')


def _run(cmd, **kwargs):
    return subprocess.run(cmd, **kwargs)


def _tail(text):
    return (text or '').strip()[-500:]


def _grantee(run=None):
    """Installing account for icacls grants; never a literal %VAR%."""
    run = run or _run
    expanded = os.path.expandvars('%USERNAME%')
    if expanded and expanded != '%USERNAME%':
        return expanded
    whoami = run(['whoami'], capture_output=True, text=True)
    owner = (whoami.stdout or '').strip()
    if owner:
        return owner
    raise SystemExit('cannot determine the installing user for key protection')


def protect_file(path, run=None):
    """Restrict path to the installing user via icacls; verify afterwards.

    Creates the file's parent with the restricted ACL first so the secret is
    never written widened-then-narrowed. Raises SystemExit naming the exact
    failure; never silently leaves an exposed key.
    """
    run = run or _run
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    grantee = _grantee(run)
    result = run(['icacls', str(path.parent), '/inheritance:r', '/grant:r',
                  grantee + ':F'], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit('cannot restrict %s: %s'
                         % (path.parent, _tail(result.stderr)))
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    result = run(['icacls', str(path), '/inheritance:r', '/grant:r',
                  grantee + ':F'], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit('cannot protect %s: %s'
                         % (path, _tail(result.stderr)))
    _winacl.check(path, run=run)


def _health(state, timeout=20):
    url = 'http://127.0.0.1:%s/%s/health' % (state['port'], state['token'])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                body = json.loads(response.read())
                if response.status == 200 and body.get('status') == 'ok':
                    return body
        except (OSError, ValueError):
            time.sleep(0.5)
    return None


class Backend:
    name = 'windows'

    def __init__(self, svc, run):
        self._svc = svc
        self._run = run

    def protect_secret(self, path):
        protect_file(path, run=self._run)

    def check(self, home):
        del home  # Stage 3 preconditions land with the Task Scheduler tasks.
        return None

    def _register(self, name, xml, home):
        # Written beside the router log directory, never into a prunable
        # release path; the XML is a registration vehicle, not a secret.
        xml_path = Path(home) / 'logs' / (name + '.task.xml')
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        xml_path.write_text(xml, encoding='utf-16')
        result = self._run(['schtasks', '/create', '/tn', name,
                            '/xml', str(xml_path), '/f'],
                           capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit('Windows task registration failed for %s: %s'
                             % (name, _tail(result.stderr or result.stdout)))

    def _task_state(self, name):
        # schtasks /query is the registration-and-running readback: a task
        # silently disabled by group policy reports here instead of being
        # assumed healthy.
        result = self._run(['schtasks', '/query', '/tn', name,
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
        del release_dir, previous  # launchers resolve `current` at exec time.
        self._register(ROUTER_TASK, render_router_xml(python, home), home)
        self._register(UPDATE_TASK, render_update_xml(python, home), home)
        self._registered_and_running(ROUTER_TASK)
        self._run_task(ROUTER_TASK)

    def restart(self, home):
        # Authenticated graceful path first: /shutdown drains in-flight
        # requests, then the one-minute recovery trigger relaunches.
        # Never taskkill /F: a forced kill strands in-flight requests.
        # Every failure below falls through to /run: a missing state file
        # or a refused shutdown still ends with a running task or a named
        # error, never a silent no-op.
        try:
            state = self._state(home)
            url = ('http://127.0.0.1:%s/%s/shutdown'
                   % (state['port'], state['token']))
            req = urllib.request.Request(url, data=b'{}', method='POST')
            with urllib.request.urlopen(req, timeout=30):
                pass
        except (OSError, ValueError, KeyError):
            pass
        self._run_task(ROUTER_TASK)

    def stop(self, home):
        result = self._run(['schtasks', '/end', '/tn', ROUTER_TASK],
                           capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit('Windows task failed to stop %s: %s'
                             % (ROUTER_TASK, _tail(result.stderr)))

    def _state(self, home):
        return json.loads((Path(home) / 'mixed-router-state.json').read_text())

    def _run_task(self, name):
        self._run(['schtasks', '/run', '/tn', name], capture_output=True)
        self._registered_and_running(name)

    def start_updates(self, home):
        del home  # The updater task runs on its own 15-minute trigger.
        return None

    def ensure_serving(self, home, state, version):
        # The installer's last act on every path: a pointer swap plus task
        # control cannot recover a task that is not registered, so verify
        # registration before trusting /health.
        self._registered_and_running(ROUTER_TASK)
        body = _health(state, timeout=180)
        if version is not None:
            return bool(body and body.get('version') == version)
        return bool(body)

    def rollback_serving_ok(self, home, state, version):
        # Matches the pre-split behavior: the launchers resolve `current`
        # at exec time, so the restored release is already live once the
        # task runs; verify it serves rather than assuming so.
        self._run(['schtasks', '/run', '/tn', ROUTER_TASK], capture_output=True)
        return bool(self.ensure_serving(home, state, version))

    def pinned_release(self, home):
        del home  # No cached in-memory command; prune freely.
        return None

    def uninstall(self, home):
        del home
        for task in (ROUTER_TASK, UPDATE_TASK):
            result = self._run(['schtasks', '/delete', '/tn', task, '/f'],
                               capture_output=True)
            if result.returncode != 0:
                raise SystemExit('Windows task survived uninstall: %s' % task)
