"""Run real schedulers only on disposable CI runners, using a fake local Codex CLI."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_scheduling', ROOT / 'plugins/scg-review/scripts/scheduling.py')
scheduling = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scheduling)


@unittest.skipUnless(os.environ.get('GITHUB_ACTIONS') == 'true' and
                     os.environ.get('SCG_TEST_NATIVE_SCHEDULER') == '1', 'disposable CI runners only')
class NativeSchedulingTest(unittest.TestCase):
    def test_migration_leaves_one_shared_schedule_that_updates_both_plugins(self):
        real_home = Path.home()
        with tempfile.TemporaryDirectory(prefix='SCG update test ') as tmp:
            home = Path(tmp)
            state, stub = home / 'versions.json', home / 'codex_stub.py'
            stub.write_text('''import json, sys
from pathlib import Path
state = Path(__file__).with_name('versions.json')
versions = json.loads(state.read_text()) if state.exists() else {}
args = sys.argv[1:]
if args[:2] == ['plugin', 'list']:
    result = {'installed': [{'pluginId': name + '@scg-agent-plugins', 'enabled': True,
        'version': versions.get(name, '0.0.0')} for name in ['scg-review', 'scg-subagents']]}
elif args[:3] == ['plugin', 'marketplace', 'list']:
    result = {'marketplaces': [{'name': 'scg-agent-plugins', 'marketplaceSource': {
        'sourceType': 'git', 'source': 'https://github.com/software-combined/SC_OpenRouter_adapter.git'}}]}
elif args[:3] == ['plugin', 'marketplace', 'upgrade']:
    result = {}
elif args[:2] == ['plugin', 'add']:
    versions[args[2].split('@')[0]] = '9.9.9'
    state.write_text(json.dumps(versions))
    result = {'pluginId': args[2], 'version': '9.9.9'}
else:
    raise SystemExit('Unexpected test CLI command')
print(json.dumps(result))
''', encoding='utf-8')
            if sys.platform == 'win32':
                codex = home / 'codex.cmd'
                codex.write_text(f'@echo off\n"{sys.executable}" "{stub}" %*\nexit /b %errorlevel%\n')
            else:
                codex = home / 'codex'
                codex.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(stub)) + ' "$@"\n')
                codex.chmod(0o755)
            config = real_home / '.config'
            names = ['scg-agent-plugins-update', 'scg-subagents-update']
            units = config / 'systemd/user'
            if sys.platform == 'win32':
                user = scheduling.windows_identity()[1]
                names = ['SCGReviewUpdate-' + user, 'SCGSubagentsUpdate-' + user]
                for name in names:
                    self.assertNotEqual(scheduling.run(['schtasks', '/query', '/tn', name]).returncode, 0)
            else:
                for name in names:
                    self.assertFalse((units / (name + '.service')).exists())
                    self.assertFalse((units / (name + '.timer')).exists())
            try:
                with patch.object(scheduling.Path, 'home', return_value=home), \
                        patch.dict(os.environ, {'XDG_CONFIG_HOME': str(config)}):
                    legacy = home / 'legacy.py'
                    legacy.write_text("print('legacy updater fixture')\n")
                    for plugin in ('scg-review', 'scg-subagents'):
                        base = home / '.local/share' / ('scg-agent-plugins' if plugin == 'scg-review' else plugin)
                        if sys.platform == 'win32':
                            scheduling.install_windows(str(codex), legacy, plugin, base)
                        else:
                            scheduling.install_linux(str(codex), legacy, plugin, base)
                    for plugin in ('scg-review', 'scg-subagents'):
                        source = ROOT / 'plugins' / plugin / 'scripts/updater.py'
                        spec = importlib.util.spec_from_file_location('native_updater', source)
                        updater = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(updater)
                        recognized = [(label, relative, hashlib.sha256(legacy.read_bytes()).hexdigest(), reused)
                                      for label, relative, _, reused in updater.LEGACY]
                        with patch.object(updater, 'LEGACY', recognized):
                            updater.install(str(codex), migrate=True)
                            updater.install(str(codex))
                    for directory in ('scg-agent-plugins', 'scg-subagents'):
                        self.assertEqual((home / '.local/share' / directory / 'updater.py.migrated').read_bytes(),
                                         legacy.read_bytes())
                if sys.platform == 'win32':
                    self.assertNotEqual(scheduling.run(['schtasks', '/query', '/tn', names[1]]).returncode, 0)
                    scheduling.run(['schtasks', '/run', '/tn', names[0]], check=True)
                    log = home / '.local/share/scg-agent-plugins/update.log'
                    for _ in range(30):
                        if log.exists() and '9.9.9; new Codex tasks' in log.read_text(encoding='utf-8'):
                            break
                        time.sleep(1)
                    self.assertIn('9.9.9; new Codex tasks', log.read_text(encoding='utf-8'))
                else:
                    self.assertFalse((units / (names[1] + '.timer')).exists())
                    scheduling.run(['systemctl', '--user', 'start', names[0] + '.service'], check=True)
                    result = scheduling.run(['systemctl', '--user', 'show', names[0] + '.service', '-p', 'Result', '--value'], check=True)
                    self.assertEqual(result.stdout.strip(), 'success')
                self.assertEqual(json.loads(state.read_text()), {'scg-review': '9.9.9', 'scg-subagents': '9.9.9'})
            finally:
                for name in names:
                    if sys.platform == 'win32':
                        scheduling.run(['schtasks', '/end', '/tn', name])
                        scheduling.run(['schtasks', '/delete', '/tn', name, '/f'])
                    else:
                        scheduling.run(['systemctl', '--user', 'disable', '--now', name + '.timer'])
                        scheduling.run(['systemctl', '--user', 'stop', name + '.service'])
                        for suffix in ('.service', '.timer'):
                            (units / (name + suffix)).unlink(missing_ok=True)
                        scheduling.run(['systemctl', '--user', 'daemon-reload'])


if __name__ == '__main__':
    unittest.main()
