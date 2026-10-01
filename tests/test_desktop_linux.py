"""Offline contract tests for read-only Linux desktop identity."""
import contextlib
import importlib.util
import io
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'claude_desktop_platform_linux_test', ROOT / 'packaging/claude_desktop_platform.py')
platform = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(platform)


def _pickle_string(value):
    raw = value.encode('utf-8')
    payload = struct.pack('<I', len(raw)) + raw + b'\0' * (-len(raw) % 4)
    return struct.pack('<I', len(payload)) + payload


def _write_asar(root, metadata, offset='0', declared_size=None, stored_offset=None):
    resources = root / 'resources'
    resources.mkdir(parents=True, exist_ok=True)
    package = json.dumps(metadata, separators=(',', ':')).encode('utf-8')
    index = json.dumps({'files': {'package.json': {
        'offset': str(offset), 'size': len(package) if declared_size is None else declared_size}}},
        separators=(',', ':'))
    header = _pickle_string(index)
    stored_offset = int(offset) if stored_offset is None else stored_offset
    archive = struct.pack('<II', 4, len(header)) + header + b'\0' * stored_offset + package
    (resources / 'app.asar').write_bytes(archive)
    return root / 'ChatGPT' if metadata.get('productName') == 'Codex' else root / 'claude-desktop'


def _executable(path, body=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if body is None:
        path.write_bytes(b'\x7fELF synthetic fixture')
    else:
        path.write_text(body, encoding='utf-8')
    path.chmod(0o755)
    return path


@unittest.skipIf(os.name == 'nt', 'synthetic fixtures require POSIX executable paths and os.getuid')
class LinuxDesktopIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data_home = self.root / 'data'
        self.applications = self.data_home / 'applications'
        self.applications.mkdir(parents=True)
        self.bin = self.root / 'bin'

    def env(self):
        return mock.patch.dict(os.environ, {
            'XDG_DATA_HOME': str(self.data_home), 'XDG_DATA_DIRS': '',
            'PATH': str(self.bin)})

    def entry(self, desktop_id, executable, kind='Application', extra=''):
        path = self.applications / (desktop_id + '.desktop')
        path.write_text('[Desktop Entry]\nType=' + kind + '\nExec=' + executable
                        + '\n' + extra,
                        encoding='utf-8')
        return path

    def test_codex_identity_reads_the_selected_package_without_launching(self):
        root = self.root / 'opt/codex-desktop'
        exe = _write_asar(root, {
            'name': 'openai-codex-electron', 'productName': 'Codex', 'version': '26.928.20755'})
        exe.parent.mkdir(parents=True, exist_ok=True)
        _executable(exe)
        self.entry('codex-desktop', str(exe))
        with self.env():
            identity = platform.app_identity(
                'linux', run=lambda *args, **kwargs: self.fail('identity ran a command'),
                app=platform.App('com.openai.codex', ()))
        self.assertEqual(identity['root'], str(root.resolve()))
        self.assertEqual(identity['exe'], str(exe.resolve()))
        self.assertEqual(identity['desktop_id'], 'codex-desktop')
        self.assertEqual(identity['package_version'], '26.928.20755')

    def test_claude_accepts_the_reported_desktop_id_and_relative_wrapper(self):
        root = self.root / 'usr/lib/claude-desktop'
        main = _write_asar(root, {
            'name': '@ant/desktop', 'productName': 'Claude', 'version': '2.16120.0'})
        marker = self.root / 'wrapper-ran'
        _executable(main, '#!/bin/sh\nprintf ran > "%s"\n' % marker)
        wrapper = _executable(self.bin / 'claude-desktop',
                              '#!/bin/sh\nexec "%s" "$@"\n' % main)
        self.entry('com.anthropic.Claude', 'claude-desktop %U')
        with self.env(), mock.patch('subprocess.run', side_effect=AssertionError('process started')):
            identity = platform.app_identity(
                'linux', run=lambda *args, **kwargs: self.fail('identity ran a command'))
        self.assertEqual(identity['root'], str(root.resolve()))
        self.assertEqual(identity['exe'], str(main.resolve()))
        self.assertEqual(identity['desktop_id'], 'com.anthropic.Claude')
        self.assertEqual(identity['package_version'], '2.16120.0')
        self.assertTrue(wrapper.is_file())
        self.assertFalse(marker.exists())

    def test_relative_wrapper_targets_are_refused_even_when_files_match_app_package(self):
        for target, root in (('../real-app/claude-desktop', self.root / 'real-app'),
                             ('./real-app/claude-desktop', self.bin / 'real-app')):
            with self.subTest(target=target):
                main = _write_asar(root, {
                    'name': '@ant/desktop', 'productName': 'Claude', 'version': '2.16120.0'})
                _executable(main)
                _executable(self.bin / 'claude-desktop',
                            '#!/bin/sh\nexec %s "$@"\n' % target)
                self.entry('com.anthropic.Claude', 'claude-desktop %U')
                with self.env():
                    with self.assertRaises(OSError):
                        platform.app_identity('linux')

    def test_env_assignment_quoted_path_and_literal_percent_escape(self):
        root = self.root / 'installed/space app'
        main = _write_asar(root, {
            'name': 'openai-codex-electron', 'productName': 'Codex', 'version': '26.928.20755'})
        _executable(main)
        self.bin.mkdir(parents=True)
        (self.bin / 'ChatGPT').symlink_to(main)
        self.entry('codex-desktop',
                   '/usr/bin/env LABEL=100%%%% PATH="%s" ChatGPT %%U %%%%' % self.bin)
        with self.env():
            identity = platform.app_identity('linux', app=platform.App('com.openai.codex', ()))
        self.assertEqual(identity['root'], str(root.resolve()))
        self.assertEqual(identity['package_version'], '26.928.20755')

    def test_hidden_xdg_override_refuses_without_falling_through(self):
        root = self.root / 'system/codex'
        exe = _write_asar(root, {
            'name': 'openai-codex-electron', 'productName': 'Codex', 'version': '1.0'})
        _executable(exe)
        system_apps = self.root / 'system-data/applications'
        system_apps.mkdir(parents=True)
        (system_apps / 'codex-desktop.desktop').write_text(
            '[Desktop Entry]\nType=Application\nExec=' + str(exe) + '\n', encoding='utf-8')
        with self.env(), mock.patch.dict(os.environ, {'XDG_DATA_DIRS': str(system_apps.parent)}):
            identity = platform.app_identity('linux', app=platform.App('com.openai.codex', ()))
        self.assertEqual(identity['root'], str(root.resolve()))
        self.entry('codex-desktop', 'ChatGPT', extra='Hidden=true\n')
        with self.env(), mock.patch.dict(os.environ, {'XDG_DATA_DIRS': str(system_apps.parent)}):
            with self.assertRaises(OSError):
                platform.app_identity('linux', app=platform.App('com.openai.codex', ()))

    def test_wrong_entry_kind_and_unsupported_field_code_refuse(self):
        root = self.root / 'opt/codex'
        exe = _write_asar(root, {
            'name': 'openai-codex-electron', 'productName': 'Codex', 'version': '1.0'})
        _executable(exe)
        self.entry('codex-desktop', str(exe), kind='Link')
        with self.env():
            with self.assertRaises(OSError):
                platform.app_identity('linux', app=platform.App('com.openai.codex', ()))
        self.entry('codex-desktop', str(exe) + ' %z')
        with self.env():
            with self.assertRaises(OSError):
                platform.app_identity('linux', app=platform.App('com.openai.codex', ()))

    def test_corrupt_asar_bounds_and_wrong_package_identity_refuse(self):
        for offset, name, corrupt in (('999999', 'openai-codex-electron', False),
                                      ('0', 'wrong-package', False), ('0',
                                      'openai-codex-electron', True)):
            root = self.root / ('app-' + str(len(list(self.root.iterdir()))))
            exe = _write_asar(root, {
                'name': name, 'productName': 'Codex', 'version': '1.0'}, offset=offset,
                stored_offset=0 if offset != '0' else None)
            _executable(exe)
            if corrupt:
                (root / 'resources/app.asar').write_bytes(b'bad archive')
            self.entry('codex-desktop', str(exe))
            with self.subTest(offset=offset, name=name, corrupt=corrupt), self.env():
                with self.assertRaises(OSError):
                    platform.app_identity('linux', app=platform.App('com.openai.codex', ()))

    def test_diagnostic_prints_nonsecret_identity_and_rejects_other_platforms(self):
        root = self.root / 'opt/codex-desktop'
        exe = _write_asar(root, {
            'name': 'openai-codex-electron', 'productName': 'Codex', 'version': '26.928.20755'})
        _executable(exe)
        self.entry('codex-desktop', str(exe))
        output = io.StringIO()
        with self.env(), mock.patch.object(platform._linux_identity.sys, 'platform', 'linux'), \
                mock.patch('subprocess.run', side_effect=AssertionError('process started')), \
                contextlib.redirect_stdout(output):
            self.assertEqual(platform._linux_identity.main(['--app', 'codex']), 0)
        identity = json.loads(output.getvalue())
        self.assertEqual(identity['desktop_id'], 'codex-desktop')
        self.assertEqual(identity['package_version'], '26.928.20755')
        self.assertNotIn(str(self.bin), output.getvalue())
        error = io.StringIO()
        with mock.patch.object(platform._linux_identity.sys, 'platform', 'darwin'), \
                contextlib.redirect_stderr(error):
            self.assertEqual(platform._linux_identity.main(['--app', 'codex']), 1)
        self.assertIn('Linux only', error.getvalue())


if __name__ == '__main__':
    unittest.main()
