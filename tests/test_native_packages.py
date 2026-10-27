"""Offline native launchers, unsigned commands, and uruntime fallback."""

import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packaging' / 'native'))
import native_build as build  # noqa: E402


class NativePackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='native package spaces ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.resources = self.root / 'Resources'
        icon = self.resources / 'router/packaging/assets/router-icon.png'
        icon.parent.mkdir(parents=True)
        icon.write_bytes(b'PNG fixture')

    def _fake_python(self, path):
        path.parent.mkdir(parents=True)
        path.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE"\n')
        path.chmod(0o755)

    @unittest.skipIf(os.name == 'nt', 'Unix shell launchers run on macOS and Linux')
    def test_launchers_use_their_own_resources_with_spaces(self):
        mac = self.root / 'Install SCG Router.app/Contents'
        launcher = mac / 'MacOS/Install SCG Router'
        launcher.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / 'packaging/native/mac-launcher.sh', launcher)
        launcher.chmod(0o755)
        resources = mac / 'Resources'
        self._fake_python(resources / 'runtime/python/bin/python3.14')
        capture = self.root / 'mac args.txt'
        subprocess.run([launcher, '--probe'], check=True,
                       env=dict(os.environ, CAPTURE=str(capture)))
        self.assertEqual(capture.read_text().splitlines(), [
            str(resources / 'router/packaging/native_setup.py'),
            '--resources', str(resources), '--probe'])

        appdir = self.root / 'SCG Router.AppDir'
        apprun = appdir / 'AppRun'
        appdir.mkdir()
        shutil.copyfile(ROOT / 'packaging/native/linux-AppRun', apprun)
        apprun.chmod(0o755)
        resources = appdir / 'Resources'
        self._fake_python(resources / 'runtime/python/bin/python3.14')
        capture = self.root / 'linux args.txt'
        subprocess.run([apprun, '--probe'], check=True,
                       env=dict(os.environ, CAPTURE=str(capture)))
        self.assertEqual(capture.read_text().splitlines(), [
            str(resources / 'router/packaging/native_setup.py'),
            '--resources', str(resources), '--probe'])

    def test_windows_installed_copy_is_its_entrypoint(self):
        script = (ROOT / 'packaging/native/windows.iss').read_text()
        self.assertIn('Filename: "{app}\\runtime\\python\\pythonw.exe"', script)
        self.assertIn('--resources ""{app}""', script)
        self.assertIn('DestDir: "{app}"', script)
        self.assertNotIn('python.exe"; Parameters:', script)
        self.assertIn("WizardForm.Caption := 'SCG Router'", script)
        self.assertIn('SetupIconFile=@ICON@', script)

    def test_both_windows_install_paths_require_accepting_the_runtime_terms(self):
        # Microsoft's Visual Studio licence (section 4.b) requires end users to agree
        # to terms protecting its runtime files before receiving them.
        terms = (ROOT / 'packaging/native/windows-runtime-terms.txt').read_text()
        rendered = []
        def iscc(argv, **kwargs):
            rendered.append(Path(argv[1]).read_text())
        with mock.patch.object(build.sys, 'platform', 'win32'), \
                mock.patch.object(build, '_make_ico'), mock.patch.object(build, 'run', side_effect=iscc):
            with self.assertRaisesRegex(ValueError, 'did not produce an EXE'):
                build.windows(self.resources, self.root, '1.3.6')
        licence = re.search(r'^LicenseFile=(.+)$', rendered[0], re.M).group(1)
        self.assertEqual(Path(licence).read_text(), terms)
        script = (ROOT / 'packaging/bootstrap.ps1').read_text()
        self.assertIn("Write-Host @'\n" + terms + "'@", script)
        self.assertLess(script.index("Read-Host 'Type ACCEPT"), script.index('$mirrorUrl" -OutFile'))

    @unittest.skipUnless(shutil.which('pwsh') or shutil.which('powershell'), 'needs PowerShell')
    def test_setup_script_downloads_no_runtime_until_the_terms_are_accepted(self):
        import functools, http.server, json, threading
        feed = self.root / 'feed'
        feed.mkdir()
        (feed / 'runtimes.json').write_text(json.dumps({'targets': {'windows/x86_64': {
            'mirror': 'runtimes/x.tar.gz', 'exec': 'python/python.exe', 'sha256': '0' * 64}}}))
        requested = []
        class Feed(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                requested.append(self.path)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Feed, directory=feed))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        shell = shutil.which('pwsh') or shutil.which('powershell')
        env = dict(os.environ, ROUTER_HOME=str(self.root / 'home'),
                   FEED_ORIGIN='http://127.0.0.1:%d' % server.server_port)
        result = subprocess.run([shell, '-NoProfile', '-File', str(ROOT / 'packaging/bootstrap.ps1')],
                                input='no\n', capture_output=True, text=True, timeout=120, env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn('terms were not accepted', ' '.join((result.stdout + result.stderr).split()))
        self.assertNotIn('/runtimes/x.tar.gz', requested)

    def test_uruntime_architecture_and_automatic_fallback(self):
        elf = bytearray(32)
        elf[:4] = b'\x7fELF'
        elf[4:6] = b'\x02\x01'
        elf[18:20] = (62).to_bytes(2, 'little')
        source = self.root / 'uruntime'
        source.write_bytes(bytes(elf) + b'URUNTIME_EXTRACT=3')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        embedded = self.root / 'embedded-runtime'
        build._uruntime(source, digest, 'x86_64', embedded)
        self.assertIn(b'URUNTIME_EXTRACT=2', embedded.read_bytes())
        with self.assertRaisesRegex(ValueError, 'architecture'):
            build._uruntime(source, digest, 'arm64', self.root / 'wrong-arch')
        with self.assertRaisesRegex(ValueError, 'pinned sha256'):
            build._uruntime(source, '0' * 64, 'x86_64', self.root / 'wrong-sha')

    def test_mac_and_windows_builds_do_not_sign(self):
        commands = []

        def fake_mac(argv, **_):
            commands.append([str(value) for value in argv])
            if argv[0] == 'hdiutil':
                Path(argv[-1]).write_bytes(b'dmg')

        def fake_icon(_source, destination):
            Path(destination).write_bytes(b'icns')

        out = self.root / 'out'
        out.mkdir()
        with mock.patch.object(build.sys, 'platform', 'darwin'), \
                mock.patch.object(build, 'run', fake_mac), \
                mock.patch.object(build, '_make_icns', fake_icon):
            dmg = build.mac(self.resources, out, '1.2.3.4', 'arm64')
        self.assertTrue(dmg.is_file())
        self.assertEqual([command[0] for command in commands], ['hdiutil'])

        def fake_inno(argv, **_):
            commands.append([str(value) for value in argv])
            script = Path(argv[-1]).read_text()
            output = Path(re.search(r'#define OutputDir "([^"]+)"', script)[1])
            (output / 'SCG-Router-Installer-1.2.3.4-Windows.exe').write_bytes(b'exe')

        with mock.patch.object(build.sys, 'platform', 'win32'), \
                mock.patch.object(build, 'run', fake_inno), \
                mock.patch.object(build, '_make_ico', fake_icon):
            exe = build.windows(self.resources, out, '1.2.3.4')
        self.assertTrue(exe.is_file())
        self.assertEqual([command[0] for command in commands],
                         ['hdiutil', 'ISCC.exe'])

    def test_linux_build_pins_tools_and_uses_uruntime(self):
        out = self.root / 'out'
        out.mkdir()
        tool = self.root / 'appimagetool'
        tool.write_bytes(b'pinned builder')
        elf = bytearray(32)
        elf[:4] = b'\x7fELF'
        elf[4:6] = b'\x02\x01'
        elf[18:20] = (62).to_bytes(2, 'little')
        runtime = self.root / 'uruntime'
        runtime.write_bytes(bytes(elf) + b'URUNTIME_EXTRACT=3')
        calls = []

        def fake_build(argv, **kwargs):
            calls.append(([str(value) for value in argv], kwargs))
            self.assertEqual(str(argv[0]), str(tool.resolve()))
            self.assertIn(b'URUNTIME_EXTRACT=2', Path(argv[2]).read_bytes())
            self.assertEqual(kwargs['env']['APPIMAGE_EXTRACT_AND_RUN'], '1')
            Path(argv[-1]).write_bytes(b'AppImage')

        with contextlib.chdir(self.root), mock.patch.object(build.sys, 'platform', 'linux'), \
                mock.patch.object(build, 'run', fake_build):
            artifact = build.linux(
                self.resources, out, '1.2.3.4', 'x86_64',
                appimagetool=Path('./appimagetool'),
                appimagetool_sha256=hashlib.sha256(tool.read_bytes()).hexdigest(),
                uruntime=runtime,
                uruntime_sha256=hashlib.sha256(runtime.read_bytes()).hexdigest())
        self.assertTrue(artifact.is_file())
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][1], '--runtime-file')
        self.assertNotIn('--sign', calls[0][0])


if __name__ == '__main__':
    unittest.main()
