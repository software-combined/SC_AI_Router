"""Isolated installs must never write the machine-wide LaunchAgents plists.

A live services incident (2026-09-12) traced to an install run against a
scratch home while the real ``~/Library/LaunchAgents`` was machine-readable:
the service labels are machine-wide, so a scratch-home run still mutates the
production jobs. This module fingerprints the real directory and proves the
mutating entry point cannot reach it, both through a fully-seamed install and
through the live-home refusal.
"""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._platform import unix_only
from tests.install_fixtures import install_mod
from tests.test_install_lifecycle import _run_install

REAL_AGENTS = Path.home() / 'Library' / 'LaunchAgents'
PLIST_GLOB = 'com.local.codex-mixed-model-router*.plist'


def _fingerprint(directory, pattern):
    return sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size)
                  for p in directory.glob(pattern))


@unix_only
class LaunchAgentsIsolationTests(unittest.TestCase):
    def test_isolated_install_never_touches_the_real_launch_agents(self):
        before = _fingerprint(REAL_AGENTS, PLIST_GLOB)

        written = []
        # The darwin backend loads its own launchd module instance and writes
        # through that copy, not ``service._launchd``.
        launchd = install_mod._platforms._darwin_mod()._launchd
        real_write = launchd.write_plist
        self.addCleanup(setattr, launchd, 'write_plist', real_write)

        def recorder(path, content):
            target = Path(path).resolve()
            written.append(target)
            if REAL_AGENTS.resolve() in target.parents:
                raise AssertionError(
                    'isolated install wrote a real LaunchAgents plist: %s' % target)
            return real_write(path, content)

        launchd.write_plist = recorder
        # Prove the detector itself works: a direct real-path write trips it.
        with self.assertRaises(AssertionError):
            recorder(REAL_AGENTS / 'com.local.codex-mixed-model-router.probe.plist', {})
        written.clear()

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            fake_agents = (Path(tmp) / 'fakehome' / 'Library' / 'LaunchAgents').resolve()
            # A full install with faked seams (faked HOME + run) must land its
            # plists under the scratch HOME, never in the real directory.
            _run_install(self, tmp, home, '1.0.0')
            # Positive control: the recorder must have seen the install's own
            # plists, so the checks below cannot pass by observing nothing.
            self.assertTrue(written, 'the isolated install wrote no plists at all')
            for target in written:
                self.assertIn(fake_agents, target.parents,
                              'isolated install wrote outside its scratch HOME: %s' % target)
            # The mutating entry point named at the real HOME must refuse the
            # scratch home before it can reach any service write.
            env = {k: v for k, v in os.environ.items() if k != 'ROUTER_LIVE_RUN'}
            with mock.patch.dict(os.environ, env, clear=True), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(SystemExit, 'scratch home'):
                    install_mod.main(['--home', str(home),
                                      '--feed', 'file:///latest.json'])

        after = _fingerprint(REAL_AGENTS, PLIST_GLOB)
        self.assertEqual(after, before,
                         'an isolated install rewrote the real LaunchAgents plists')
        self.assertEqual([t for t in written if REAL_AGENTS.resolve() in t.parents],
                         [], 'an isolated install wrote into the real LaunchAgents')


if __name__ == '__main__':
    unittest.main()
