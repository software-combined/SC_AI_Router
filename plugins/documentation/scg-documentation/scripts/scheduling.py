"""Native per-user updater schedules; bundled unchanged in both SCG plugins."""
import csv
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import xml.etree.ElementTree as ET

def run(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, timeout=30,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), **kwargs)


def check_files(files, plugin):
    for path, body in files.items():
        if path.exists() and path.read_bytes() != body:
            raise ValueError('Existing updater files differ; preserve them and arrange an explicit migration.')


def write_files(files, plugin):
    check_files(files, plugin)
    for path, body in files.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(body)


def quote_unit(value, command=False):
    value = str(value).replace('%', '%%')
    return json.dumps(value.replace('$', '$$') if command else value, ensure_ascii=False)


def install_linux(codex, source, plugin, base):
    run(['systemctl', '--user', 'show-environment'], check=True)
    name = 'scg-agent-plugins-update' if plugin == 'scg-review' else 'scg-subagents-update'
    units = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'systemd/user'
    if not units.is_absolute():
        raise ValueError('XDG_CONFIG_HOME must be an absolute path.')
    script = base / 'updater.py'
    command = ' '.join(quote_unit(arg, True) for arg in
                       (sys.executable, script, 'run', '--codex', codex))
    service = ('[Unit]\nDescription=Update ' + plugin + '\n[Service]\nType=oneshot\n'
               'ExecStart=' + command + '\nEnvironment=' + quote_unit('PATH=' + os.environ.get('PATH', '/usr/bin:/bin'))
               + '\nTimeoutStartSec=15min\nUMask=0077\n')
    timer = ('[Unit]\nDescription=Daily ' + plugin + ' updates\n[Timer]\n'
             'OnStartupSec=5min\nOnUnitInactiveSec=24h\n'
             '[Install]\nWantedBy=timers.target\n')
    write_files({script: source.read_bytes(), units / (name + '.service'): service.encode(),
                 units / (name + '.timer'): timer.encode()}, plugin)
    run(['systemctl', '--user', 'daemon-reload'], check=True)
    run(['systemctl', '--user', 'enable', '--now', name + '.timer'], check=True)
    run(['systemctl', '--user', 'is-enabled', name + '.timer'], check=True)
    run(['systemctl', '--user', 'is-active', name + '.timer'], check=True)
    return plugin + ' updater configured for user-session startup and every 24 hours.'


def windows_xml(python, script, codex, user):
    task = ET.Element('Task', version='1.2', xmlns='http://schemas.microsoft.com/windows/2004/02/mit/task')
    triggers = ET.SubElement(task, 'Triggers')
    logon = ET.SubElement(triggers, 'LogonTrigger')
    ET.SubElement(logon, 'Enabled').text = 'true'
    ET.SubElement(logon, 'UserId').text = user
    daily = ET.SubElement(triggers, 'CalendarTrigger')
    ET.SubElement(daily, 'StartBoundary').text = '2000-01-01T09:00:00'
    ET.SubElement(daily, 'Enabled').text = 'true'
    ET.SubElement(ET.SubElement(daily, 'ScheduleByDay'), 'DaysInterval').text = '1'
    principal = ET.SubElement(ET.SubElement(task, 'Principals'), 'Principal', id='Author')
    for key, value in [('UserId', user), ('LogonType', 'InteractiveToken'), ('RunLevel', 'LeastPrivilege')]:
        ET.SubElement(principal, key).text = value
    settings = ET.SubElement(task, 'Settings')
    for key, value in [('MultipleInstancesPolicy', 'IgnoreNew'), ('DisallowStartIfOnBatteries', 'false'),
                       ('StopIfGoingOnBatteries', 'false'), ('StartWhenAvailable', 'true'),
                       ('Enabled', 'true'), ('ExecutionTimeLimit', 'PT15M')]:
        ET.SubElement(settings, key).text = value
    action = ET.SubElement(ET.SubElement(task, 'Actions', Context='Author'), 'Exec')
    ET.SubElement(action, 'Command').text = str(python)
    ET.SubElement(action, 'Arguments').text = subprocess.list2cmdline([str(script), 'run', '--codex', codex])
    return ET.tostring(task, encoding='utf-16', xml_declaration=True)


def task_contract(xml, identity=None):
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError('Could not parse Windows task readback.') from exc
    for element in root.iter():
        element.tag = element.tag.rsplit('}', 1)[-1]
    # schtasks may return the current account name instead of its SID.
    if identity:
        account, sid = identity
        for field in ('Principals/Principal/UserId', 'Triggers/LogonTrigger/UserId'):
            node = root.find(field)
            if node is not None and node.text and node.text.casefold() == account.casefold():
                node.text = sid
    # Windows omits these default values when exporting a registered task.
    defaults = {
        'Principals/Principal/RunLevel': 'LeastPrivilege',
        'Triggers/LogonTrigger/Enabled': 'true',
        'Triggers/CalendarTrigger/Enabled': 'true',
        'Settings/Enabled': 'true',
    }
    fields = ('Principals/Principal/UserId', 'Principals/Principal/LogonType',
              'Principals/Principal/RunLevel', 'Actions/Exec/Command', 'Actions/Exec/Arguments',
              'Triggers/LogonTrigger/UserId', 'Triggers/LogonTrigger/Enabled',
              'Triggers/CalendarTrigger/StartBoundary', 'Triggers/CalendarTrigger/Enabled',
              'Triggers/CalendarTrigger/ScheduleByDay/DaysInterval',
              'Settings/MultipleInstancesPolicy', 'Settings/DisallowStartIfOnBatteries',
              'Settings/StopIfGoingOnBatteries', 'Settings/StartWhenAvailable',
              'Settings/Enabled', 'Settings/ExecutionTimeLimit')
    shape = tuple(tuple(sorted(child.tag for child in root.findall(group + '/*'))) for group in
                  ('Principals', 'Actions', 'Triggers'))
    return shape, tuple(root.findtext(field, defaults.get(field)) for field in fields)


def windows_identity():
    identity = run(['whoami', '/user', '/fo', 'csv', '/nh'], check=True)
    rows = list(csv.reader(identity.stdout.splitlines()))
    if len(rows) != 1 or len(rows[0]) != 2:
        raise ValueError('Could not identify the installing Windows user.')
    user = rows[0][1]
    if not user.startswith('S-1-') or not all(c.isdigit() or c in 'S-' for c in user):
        raise ValueError('Could not identify the installing Windows user.')
    return rows[0]


def install_windows(codex, source, plugin, base):
    identity = windows_identity()
    user = identity[1]
    name = ('SCGReviewUpdate-' if plugin == 'scg-review' else 'SCGSubagentsUpdate-') + user
    python = Path(sys.executable).with_name('pythonw.exe')
    if not python.is_file():
        raise ValueError('Windows scheduling requires pythonw.exe beside the Python interpreter.')
    script, xml_path = base / 'updater.py', base / 'update.task.xml'
    definition = windows_xml(python, script, codex, user)
    expected = task_contract(definition, identity)
    existing = run(['schtasks', '/query', '/tn', name, '/xml'])
    if existing.returncode == 0 and task_contract(existing.stdout, identity) != expected:
        raise ValueError('Existing Windows task differs; preserve it and arrange an explicit migration.')
    write_files({script: source.read_bytes(), xml_path: definition}, plugin)
    if existing.returncode != 0:
        # No /F: even a registration race must not overwrite somebody else's task.
        run(['schtasks', '/create', '/tn', name, '/xml', str(xml_path)], check=True)
    actual = run(['schtasks', '/query', '/tn', name, '/xml'], check=True)
    if task_contract(actual.stdout, identity) != expected:
        raise ValueError('Windows task readback did not match the requested schedule.')
    return plugin + ' updater configured for logon and daily at 09:00 while signed in.'


def install_macos(codex, source, plugin, label, base):
    script = base / 'updater.py'
    plist = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
    definition = {
        'Label': label, 'ProgramArguments': [sys.executable, str(script), 'run', '--codex', codex],
        'EnvironmentVariables': {'PATH': os.environ.get('PATH', '/usr/bin:/bin')},
        'RunAtLoad': True, 'StartInterval': 86400, 'ProcessType': 'Background',
        'StandardOutPath': str(base / 'update.log'), 'StandardErrorPath': str(base / 'update-error.log'),
    }
    # A changed shell PATH alone is not a reason to replace a working job.
    if plist.exists():
        current = plistlib.loads(plist.read_bytes())
        if {k: v for k, v in current.items() if k != 'EnvironmentVariables'} == {
                k: v for k, v in definition.items() if k != 'EnvironmentVariables'}:
            definition = current
    gui = f'gui/{os.getuid()}'
    check_files({script: source.read_bytes(), plist: plistlib.dumps(definition)}, plugin)
    loaded = run(['launchctl', 'print', f'{gui}/{label}']).returncode == 0
    if loaded and (not script.exists() or not plist.exists()):
        raise ValueError('An existing service has incomplete owned files; manual reconciliation required.')
    write_files({script: source.read_bytes(), plist: plistlib.dumps(definition)}, plugin)
    if not loaded:
        run(['launchctl', 'bootstrap', gui, str(plist)], check=True)
    return plugin + (' updater already configured' if loaded else ' updater configured') + ' for login and every 24 hours.'


def install(codex, source, plugin, label):
    # Either plugin configures the same marketplace-wide runner and schedule.
    plugin = 'scg-review'
    base = Path.home() / '.local/share/scg-agent-plugins'
    if sys.platform == 'darwin':
        return install_macos(codex, source, plugin, label, base)
    if sys.platform == 'linux':
        return install_linux(codex, source, plugin, base)
    if sys.platform == 'win32':
        return install_windows(codex, source, plugin, base)
    raise ValueError('Scheduling supports macOS, Linux with a systemd user manager, and Windows.')
