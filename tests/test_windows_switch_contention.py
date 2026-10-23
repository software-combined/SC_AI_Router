"""A large Windows app tree can switch after a scheduled update releases its lock."""
import contextlib
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_codex_desktop_switch import switcher


class WindowsSwitchContentionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.home, self.config, self.app = root / 'router', root / 'config.toml', root / 'StorePackage'
        self.home.mkdir()
        exe = self.app / 'app/ChatGPT.exe'
        self.cli = exe.parent / 'resources/codex.exe'
        self.cli.parent.mkdir(parents=True)
        self.cli.write_bytes(b'MZ fixture')
        exe.touch()
        state = dict(port=4321, token='fixture', clients='codex', openai_mode='subscription')
        (self.home / 'mixed-router-state.json').write_text(json.dumps(state))
        block = switcher._blocks.build(self.home, state, 'subscription', False, 'default')
        switcher._blocks._codex.write_receipt(self.home, self.config, block, None, 'subscription', '')
        self.config.write_text(block)
        self.identity = dict(root=str(self.app), exe=str(exe), user='fixture', app='Codex!App')
        labels = ['ChatGPT.exe'] * 14 + ['conhost.exe'] * 13 + ['node.exe'] * 7
        labels += ['node_repl.exe'] * 6 + ['cmd.exe'] * 4 + ['codex.exe', 'computer-use.exe']
        self.rows = [dict(pid=index + 10, parent=1 if index == 0 else 10,
            user='fixture', born='fixture', exe=str(exe) if name == 'ChatGPT.exe'
            else 'C:/runtime/' + name) for index, name in enumerate(labels)]
        self.snapshots, self.budgets, self.waits = iter([self.rows, []]), [], []
        self.on_wait, self.cancel_wait = lambda: None, False
        owner = self
        class Progress:
            def __init__(self, text, **kwargs):
                owner.waits.append(text)
                self.cancelled = False
            def __enter__(self):
                owner.on_wait()
                return self
            def __exit__(self, *_):
                self.cancelled = owner.cancel_wait
        self.enterContext(mock.patch.object(switcher, '_dialog', SimpleNamespace(Progress=Progress), create=True))
        self.enterContext(mock.patch.object(switcher.sys, 'platform', 'win32'))
        self.ops = switcher._platform
        self.enterContext(mock.patch.object(self.ops, 'app_identity', return_value=self.identity))
        self.confirm = self.enterContext(mock.patch.object(self.ops, 'confirm', return_value=True))
        self.reopen = self.enterContext(mock.patch.object(self.ops, 'open_app',
                                       return_value=SimpleNamespace(returncode=0)))

    def run_command(self, argv, **kwargs):
        if argv == [str(self.cli), '--version']:
            return SimpleNamespace(returncode=0, stdout='codex-cli 0.163.0-alpha.11', stderr='')
        if 'Get-CimInstance Win32_Process' in argv[-1]:
            self.budgets.append(kwargs['timeout'])
            if kwargs['timeout'] < 12.3:
                raise subprocess.TimeoutExpired('fixture snapshot', kwargs['timeout'])
            return SimpleNamespace(returncode=0, stdout=json.dumps(next(self.snapshots)), stderr='')
        if 'CloseMainWindow()' in argv[-1]:
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        raise AssertionError('Unexpected command')

    def switch(self):
        return switcher.switch(self.home, run=self.run_command,
                               prove=lambda _: True, ready=lambda _: True)

    def test_forty_six_process_tree_has_its_own_budget_and_switches(self):
        self.assertEqual(self.switch(), 'switched')
        self.assertEqual(len(self.rows), 46)
        self.assertEqual(len(self.budgets), 2)
        self.assertTrue(all(12.3 < budget <= 60 for budget in self.budgets))
        self.reopen.assert_called_once()
        self.assertEqual(self.waits, [])

    def test_waits_for_express_holder_then_checks_fresh_settings_and_large_tree(self):
        acquired, release, finished = threading.Event(), threading.Event(), threading.Event()
        def update():
            with switcher._service.install_lock(self.home) as held:
                if held:
                    acquired.set()
                    release.wait(5)
            finished.set()
        thread = threading.Thread(target=update)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(release.set)
        self.assertTrue(acquired.wait(5))
        def release_update():
            self.config.write_text(self.config.read_text() + '\n# edit during update\n')
            release.set()
            self.assertTrue(finished.wait(5))
        self.on_wait = release_update
        self.assertEqual(self.switch(), 'switched')
        self.assertEqual(len(self.waits), 1)
        self.assertIn('Waiting for SCG Router', self.waits[0])
        self.assertTrue(self.config.read_text().endswith('# edit during update\n'))
        thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_wait_timeout_refuses_without_quitting_or_changing_settings(self):
        before = self.config.read_bytes(), (self.home / 'activation.json').read_bytes()
        @contextlib.contextmanager
        def busy(*_, **kwargs):
            yield False
        with mock.patch.object(switcher._service, 'install_lock', side_effect=busy) as lock:
            with self.assertRaisesRegex(switcher.SwitchError, 'updating'):
                self.switch()
        self.assertEqual(lock.call_args.kwargs['wait'], 60)
        self.assertEqual((self.config.read_bytes(), (self.home / 'activation.json').read_bytes()), before)
        self.confirm.assert_not_called()
        self.reopen.assert_not_called()

    def test_cancel_during_wait_keeps_codex_and_settings_unchanged(self):
        self.cancel_wait = True
        before = self.config.read_bytes(), (self.home / 'activation.json').read_bytes()
        @contextlib.contextmanager
        def lock(*_, **kwargs):
            yield bool(kwargs.get('wait'))
        with mock.patch.object(switcher._service, 'install_lock', side_effect=lock):
            self.assertIsNone(self.switch())
        self.assertEqual((self.config.read_bytes(), (self.home / 'activation.json').read_bytes()), before)
        self.confirm.assert_not_called()

    def test_busy_installer_and_other_platforms_refuse(self):
        lock = switcher._service.install_lock
        with lock(self.home) as held:
            self.assertTrue(held)
            with mock.patch.object(switcher._service, 'install_lock',
                    side_effect=lambda home, **_: lock(home)):
                with self.assertRaisesRegex(switcher.SwitchError, 'updating'):
                    self.switch()
        with mock.patch.object(switcher.sys, 'platform', 'freebsd'):
            with self.assertRaisesRegex(switcher.SwitchError, 'on Mac'):
                self.switch()


if __name__ == '__main__':
    unittest.main()
