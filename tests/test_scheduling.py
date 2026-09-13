import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'plugins/scg-review/scripts/updater.py'
HELPER = SOURCE.with_name('scheduling.py')
spec = importlib.util.spec_from_file_location('scheduling', HELPER)
scheduling = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scheduling)


class SchedulingTest(unittest.TestCase):
    def test_both_plugins_ship_the_same_scheduler(self):
        self.assertEqual(HELPER.read_bytes(),
                         (ROOT / 'plugins/scg-subagents/scripts/scheduling.py').read_bytes())

    def test_either_plugin_registers_the_same_enabled_active_daily_timer(self):
        with tempfile.TemporaryDirectory(prefix='scg $cash %test ') as tmp, \
                patch.object(scheduling.Path, 'home', return_value=Path(tmp)), \
                patch.dict(os.environ, {'XDG_CONFIG_HOME': str(Path(tmp) / 'config')}), \
                patch.object(scheduling.sys, 'platform', 'linux'), \
                patch.object(scheduling, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            for plugin, name in [('scg-review', 'scg-agent-plugins-update'),
                                 ('scg-subagents', 'scg-agent-plugins-update')]:
                scheduling.install('/path with spaces/codex', SOURCE, plugin, 'unused')
                units = Path(tmp) / 'config/systemd/user'
                service = (units / (name + '.service')).read_text()
                timer = (units / (name + '.timer')).read_text()
                self.assertIn('$$cash %%test', service)
                self.assertIn('"/path with spaces/codex"', service)
                self.assertIn('OnStartupSec=5min', timer)
                self.assertIn('OnUnitInactiveSec=24h', timer)
                run.assert_any_call(['systemctl', '--user', 'enable', '--now', name + '.timer'], check=True)
                run.assert_any_call(['systemctl', '--user', 'is-enabled', name + '.timer'], check=True)
                run.assert_any_call(['systemctl', '--user', 'is-active', name + '.timer'], check=True)
                before = (units / (name + '.service')).read_bytes()
                scheduling.install('/path with spaces/codex', SOURCE, plugin, 'unused')
                self.assertEqual((units / (name + '.service')).read_bytes(), before)
            self.assertFalse((units / 'scg-subagents-update.timer').exists())

    def test_linux_without_user_manager_does_not_write_files(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(scheduling, 'run', side_effect=subprocess.CalledProcessError(1, ['systemctl'])):
            base = Path(tmp) / 'owned'
            with self.assertRaises(subprocess.CalledProcessError):
                scheduling.install_linux('/codex', SOURCE, 'scg-review', base)
            self.assertFalse(base.exists())

    def test_differing_runner_requires_migration_and_preserves_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / 'updater.py'
            script.write_bytes(b'approved previous runner')
            for content in (b'approved previous runner', b'user customisation'):
                script.write_bytes(content)
                with self.assertRaisesRegex(ValueError, 'files differ'):
                    scheduling.write_files({script: b'new installer', Path(tmp) / 'new': b'data'}, 'scg-review')
                self.assertEqual(script.read_bytes(), content)
                self.assertFalse((Path(tmp) / 'new').exists())

    def test_windows_registration_is_scoped_quoted_and_idempotent(self):
        with tempfile.TemporaryDirectory(prefix='scg & spaced ') as tmp:
            home = Path(tmp)
            python = home / 'Python Home/python.exe'
            python.parent.mkdir()
            python.with_name('pythonw.exe').touch()
            tasks, calls = {}, []

            def run(args, **kwargs):
                calls.append(args)
                if args[0] == 'whoami':
                    return subprocess.CompletedProcess(args, 0, '"DOMAIN\\User","S-1-5-21-123"\n')
                name = args[args.index('/tn') + 1]
                if '/create' in args:
                    self.assertNotIn('/f', [arg.lower() for arg in args])
                    requested = Path(args[-1]).read_text(encoding='utf-16')
                    # Native schtasks readback omits defaults and resolves the logon SID.
                    tasks[name] = requested.replace('<RunLevel>LeastPrivilege</RunLevel>', '').replace(
                        '<Enabled>true</Enabled>', '').replace(
                        '<UserId>S-1-5-21-123</UserId>', '<UserId>DOMAIN\\User</UserId>', 1)
                result = subprocess.CompletedProcess(args, 0 if name in tasks else 1, tasks.get(name, ''))
                if kwargs.get('check') and result.returncode:
                    raise subprocess.CalledProcessError(result.returncode, args)
                return result

            with patch.object(scheduling.Path, 'home', return_value=home), \
                    patch.object(scheduling.sys, 'executable', str(python)), \
                    patch.object(scheduling.sys, 'platform', 'win32'), \
                    patch.object(scheduling, 'run', side_effect=run):
                for plugin in ('scg-review', 'scg-subagents'):
                    scheduling.install('C:\\Program Files\\Codex\\codex.cmd', SOURCE, plugin, 'unused')
                    scheduling.install('C:\\Program Files\\Codex\\codex.cmd', SOURCE, plugin, 'unused')
                self.assertEqual(sum('/create' in args for args in calls), 1)
                for name, xml in tasks.items():
                    self.assertTrue(name.endswith('S-1-5-21-123'))
                    root = ET.fromstring(xml)
                    self.assertEqual(root.findtext('.//{*}LogonTrigger/{*}UserId'), 'DOMAIN\\User')
                    self.assertEqual(root.findtext('.//{*}LogonType'), 'InteractiveToken')
                    self.assertIsNone(root.findtext('.//{*}RunLevel'))
                    self.assertEqual(root.findtext('.//{*}DaysInterval'), '1')
                    self.assertIn('pythonw.exe', root.findtext('.//{*}Command'))
                    self.assertIn('"C:\\Program Files\\Codex\\codex.cmd"', root.findtext('.//{*}Arguments'))
                name = next(iter(tasks))
                tasks[name] = tasks[name].replace('</Principal>', '<RunLevel>HighestAvailable</RunLevel></Principal>')
                before = len(calls)
                with self.assertRaisesRegex(ValueError, 'task differs'):
                    scheduling.install('C:\\Program Files\\Codex\\codex.cmd', SOURCE, 'scg-review', 'unused')
                self.assertFalse(any('/create' in args for args in calls[before:]))

    def test_windows_readback_rejects_changed_command_or_additional_action(self):
        xml = scheduling.windows_xml('C:\\Python\\pythonw.exe', 'C:\\User\\updater.py', 'C:\\codex.exe', 'S-1-5-21-123')
        contract = scheduling.task_contract(xml)
        text = xml.decode('utf-16')
        self.assertNotEqual(contract, scheduling.task_contract(text.replace('codex.exe', 'other.exe')))
        self.assertNotEqual(contract, scheduling.task_contract(text.replace('</Actions>', '<Exec/></Actions>')))
        with self.assertRaisesRegex(ValueError, 'parse'):
            scheduling.task_contract('not XML')

    def test_windows_normalization_rejects_foreign_users_privilege_and_disabled_tasks(self):
        sid, account = 'S-1-5-21-123', 'DOMAIN\\User'
        requested = scheduling.windows_xml('pythonw.exe', 'updater.py', 'codex.cmd', sid)
        actual = requested.decode('utf-16').replace('<RunLevel>LeastPrivilege</RunLevel>', '').replace(
            '<Enabled>true</Enabled>', '').replace(
            '<UserId>' + sid + '</UserId>', '<UserId>domain\\user</UserId>', 1)
        expected = scheduling.task_contract(requested)
        self.assertEqual(expected, scheduling.task_contract(actual, (account, sid)))
        for changed in (
            actual.replace('domain\\user', 'DOMAIN\\Other'),
            actual.replace('domain\\user', ''),
            actual.replace(sid, 'S-1-5-21-999'),
            actual.replace('</Principal>', '<RunLevel>HighestAvailable</RunLevel></Principal>'),
            actual.replace('<LogonTrigger>', '<LogonTrigger><Enabled>false</Enabled>'),
            actual.replace('<CalendarTrigger>', '<CalendarTrigger><Enabled>false</Enabled>'),
            actual.replace('<Settings>', '<Settings><Enabled>false</Enabled>'),
        ):
            with self.subTest(changed=changed):
                self.assertNotEqual(expected, scheduling.task_contract(changed, (account, sid)))


if __name__ == '__main__':
    unittest.main()
