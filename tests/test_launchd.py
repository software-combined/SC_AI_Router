"""launchd job lifecycle: converge on the domain, never trust one return code.

The outage this file protects against: `launchctl bootout` returns 0 while the
job is still tearing down, so the `bootstrap` issued straight after it fails
with error 5 and the label ends up loaded nowhere. From there a pointer
rollback plus `launchctl kill TERM` is a no-op -- KeepAlive has no job to keep
alive -- so the machine silently loses the router and every later update run
reports a misleading "failed health check" against a router that was never
given the chance to answer.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._platform import unix_only
from tests.fakes import LaunchdDomain

ROOT = Path(__file__).resolve().parents[1]


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'packaging' / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


launchd = _load('router_launchd_under_test', 'launchd.py')
LABEL = 'com.local.codex-mixed-model-router'


def _recorder(domain):
    """Wrap a domain, recording whether the label was loaded at each call."""
    seen = []

    def run(cmd, **kwargs):
        seen.append((list(cmd), domain.loaded(LABEL)))
        return domain(cmd, **kwargs)

    return run, seen


def _agents(tmp):
    agents = Path(tmp) / 'LaunchAgents'
    agents.mkdir(parents=True, exist_ok=True)
    (agents / (LABEL + '.plist')).write_bytes(b'<plist/>')
    return agents


@unix_only
class UnloadTests(unittest.TestCase):
    def test_waits_for_the_label_to_leave_the_domain(self):
        # bootout reports success on the first call; the label only disappears
        # two polls later, exactly as a draining router behaves.
        domain = LaunchdDomain().reset(unload_lag=2)
        run, seen = _recorder(domain)
        self.assertTrue(launchd.unload(run, 501, LABEL, sleep=lambda *_: None))
        self.assertFalse(domain.loaded(LABEL))
        prints = [cmd for cmd, _ in seen if cmd[1] == 'print']
        self.assertGreaterEqual(len(prints), 2,
                                'unload must poll until the label is really gone')

    def test_returns_false_when_the_job_never_goes_away(self):
        domain = LaunchdDomain().reset(unload_lag=10 ** 6)
        run, _seen = _recorder(domain)
        self.assertFalse(launchd.unload(run, 501, LABEL, timeout=0,
                                        sleep=lambda *_: None))


@unix_only
class LoadTests(unittest.TestCase):
    def test_retries_a_bootstrap_that_lost_the_teardown_race(self):
        with tempfile.TemporaryDirectory() as tmp:
            domain = LaunchdDomain().reset(unloaded={LABEL}, bootstrap_failures=1)
            run, seen = _recorder(domain)
            self.assertTrue(launchd.load(run, 501, LABEL, agents=_agents(tmp),
                                         sleep=lambda *_: None))
            straps = [cmd for cmd, _ in seen if cmd[1] == 'bootstrap']
            self.assertEqual(len(straps), 2, 'error 5 must be retried, not fatal')

    def test_returns_false_when_bootstrap_never_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            domain = LaunchdDomain().reset(unloaded={LABEL}, bootstrap_failures=10 ** 6)
            run, _seen = _recorder(domain)
            self.assertFalse(launchd.load(run, 501, LABEL, agents=_agents(tmp),
                                          timeout=0, sleep=lambda *_: None))

    def test_no_op_when_already_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            domain = LaunchdDomain().reset()
            run, seen = _recorder(domain)
            self.assertTrue(launchd.load(run, 501, LABEL, agents=_agents(tmp)))
            self.assertFalse([cmd for cmd, _ in seen if cmd[1] == 'bootstrap'],
                             'a loaded job must not be bootstrapped again')


@unix_only
class ReloadTests(unittest.TestCase):
    def test_never_bootstraps_while_the_old_job_is_still_loaded(self):
        # The defect in one assertion: a bootstrap issued against a label that
        # launchd still knows about is the call that returns error 5.
        with tempfile.TemporaryDirectory() as tmp:
            domain = LaunchdDomain().reset(unload_lag=3)
            run, seen = _recorder(domain)
            self.assertTrue(launchd.reload_job(run, 501, LABEL, agents=_agents(tmp),
                                               sleep=lambda *_: None))
            self.assertTrue(domain.loaded(LABEL))
            early = [cmd for cmd, was_loaded in seen
                     if cmd[1] == 'bootstrap' and was_loaded]
            self.assertFalse(early, 'bootstrap must wait for the label to be gone')

    def test_fails_closed_when_the_old_job_survives(self):
        # A surviving stale job must never read as a successful reload: `load`
        # would see the label present and report success for the wrong process.
        with tempfile.TemporaryDirectory() as tmp:
            domain = LaunchdDomain().reset(unload_lag=10 ** 6)
            run, seen = _recorder(domain)
            self.assertFalse(launchd.reload_job(run, 501, LABEL, agents=_agents(tmp),
                                                unload_timeout=0,
                                                sleep=lambda *_: None))
            self.assertFalse([cmd for cmd, _ in seen if cmd[1] == 'bootstrap'],
                             'a failed unload must not proceed to bootstrap')


@unix_only
class LoadedCommandTests(unittest.TestCase):
    def test_reads_the_whole_in_memory_command(self):
        # Reading argv[0] alone is what hid a changed launcher path: the
        # interpreter matched, so the stale command stayed loaded.
        argv = ['/opt/homebrew/bin/python3.14', '/home/update_launch.py']
        domain = LaunchdDomain().reset(commands={LABEL: argv})
        self.assertEqual(launchd.loaded_command(domain, 501, LABEL), argv)

    def test_falls_back_to_the_bare_program_with_no_arguments_block(self):
        domain = LaunchdDomain().reset(program='/opt/homebrew/bin/python3.14')
        self.assertEqual(launchd.loaded_command(domain, 501, LABEL),
                         ['/opt/homebrew/bin/python3.14'])

    def test_none_when_the_label_is_not_loaded(self):
        domain = LaunchdDomain().reset(unloaded={LABEL})
        self.assertIsNone(launchd.loaded_command(domain, 501, LABEL))

    def test_records_what_bootstrap_actually_loaded_not_the_file_after(self):
        # launchd keeps the command it read at bootstrap; rewriting the plist
        # afterwards changes nothing until the job is reloaded.
        import plistlib
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / 'LaunchAgents'
            agents.mkdir()
            path = agents / (LABEL + '.plist')
            first = ['/py', '/old/install.py']
            path.write_bytes(plistlib.dumps({'Label': LABEL,
                                             'ProgramArguments': first}))
            domain = LaunchdDomain().reset(unloaded={LABEL})
            self.assertTrue(launchd.load(domain, 501, LABEL, agents=agents))
            path.write_bytes(plistlib.dumps(
                {'Label': LABEL, 'ProgramArguments': ['/py', '/new/launch.py']}))
            self.assertEqual(launchd.loaded_command(domain, 501, LABEL), first,
                             'a rewritten plist must not change the loaded command')


@unix_only
class UpdateLauncherTests(unittest.TestCase):
    """The updater entry point must resolve `current` at exec time."""

    def _home(self, tmp, version='1.2.3', pointer=None):
        home = Path(tmp) / 'home'
        (home / 'releases' / version / 'packaging').mkdir(parents=True)
        (home / 'releases' / version / 'packaging' / 'install.py').write_text(
            'import json, sys, os\n'
            'open(os.environ["ARGV_OUT"], "w").write(json.dumps(sys.argv))\n')
        (home / 'current').write_text((pointer or version) + '\n')
        launcher = home / 'update_launch.py'
        launcher.write_bytes((ROOT / 'packaging' / 'update_launch.py').read_bytes())
        return home, launcher

    def _run(self, launcher, out):
        env = dict(os.environ, ARGV_OUT=str(out))
        return subprocess.run([sys.executable, str(launcher)], env=env,
                              capture_output=True, text=True)

    def test_invokes_the_installer_of_the_release_current_points_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, launcher = self._home(tmp)
            out = Path(tmp) / 'argv.json'
            result = self._run(launcher, out)
            self.assertEqual(result.returncode, 0, result.stderr)
            import json
            argv = json.loads(out.read_text())
            # The launcher resolves its own location, so compare resolved
            # paths: on macOS /var/folders is a symlink into /private.
            self.assertEqual(
                Path(argv[0]),
                (home / 'releases' / '1.2.3' / 'packaging' / 'install.py').resolve())
            self.assertIn('--check-update', argv)
            self.assertEqual(Path(argv[argv.index('--home') + 1]), home.resolve())

    def test_follows_the_pointer_after_an_update(self):
        # The whole point: no plist rewrite is needed for the updater to start
        # running a newer release's installer.
        with tempfile.TemporaryDirectory() as tmp:
            home, launcher = self._home(tmp)
            newer = home / 'releases' / '9.9.9' / 'packaging'
            newer.mkdir(parents=True)
            (newer / 'install.py').write_text(
                'import json, sys, os\n'
                'open(os.environ["ARGV_OUT"], "w").write(json.dumps(sys.argv))\n')
            (home / 'current').write_text('9.9.9\n')
            out = Path(tmp) / 'argv.json'
            self.assertEqual(self._run(launcher, out).returncode, 0)
            import json
            self.assertEqual(Path(json.loads(out.read_text())[0]),
                             (newer / 'install.py').resolve())

    def test_fails_closed_when_the_release_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            _home, launcher = self._home(tmp, pointer='0.0.0')
            result = self._run(launcher, Path(tmp) / 'argv.json')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('release missing', result.stderr)

    def test_pointer_content_cannot_escape_the_releases_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            _home, launcher = self._home(tmp, pointer='../../../etc')
            result = self._run(launcher, Path(tmp) / 'argv.json')
            self.assertNotEqual(result.returncode, 0)


class ServiceBindingTests(unittest.TestCase):
    # Plan 103: the launchd helpers moved to launchd.py, but packaging/install.py
    # binds them from service at import time. Pin all nine so a future move
    # cannot silently break the installer's module-level seams.
    BOUND = ('main_plist_needs_reload', 'same_interpreter', 'ensure_updater',
             'loaded_updater_release', 'reload_main_service', 'render_plist',
             'render_update_plist', 'restart_service', 'write_plist')

    def test_installer_bindings_resolve_from_service(self):
        from tests.test_install import install_mod
        for name in self.BOUND:
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(install_mod._svc, name)), name)
                self.assertTrue(callable(getattr(install_mod, name)), name)


class InterpreterIdentityTests(unittest.TestCase):
    """Two spellings of one binary must not force a destructive reload."""

    def test_symlinked_spellings_are_the_same_interpreter(self):
        from tests.test_install import install_mod
        if os.name == 'nt':
            self.skipTest('symlink creation needs elevation on Windows')
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / 'Cellar' / 'python3.14'
            real.parent.mkdir(parents=True)
            real.write_text('#!/bin/sh\n')
            link = Path(tmp) / 'bin-python3.14'
            os.symlink(real, link)
            # This is the live pair that made every run take the reload path:
            # /opt/homebrew/bin/python3.14 vs
            # /opt/homebrew/opt/python@3.14/bin/python3.14.
            self.assertTrue(install_mod.same_interpreter(str(link), str(real)))
            self.assertFalse(install_mod.same_interpreter(str(real), 'python3.14'))
            self.assertFalse(install_mod.same_interpreter(None, str(real)))


@unix_only
class EnsureServingTests(unittest.TestCase):
    """The installer must never exit leaving no loaded router behind."""

    def test_bootstraps_a_missing_job_before_reporting_health(self):
        from tests.test_install import _patch_attrs, install_mod
        with tempfile.TemporaryDirectory() as tmp:
            domain = LaunchdDomain().reset(unloaded={LABEL})
            calls = []

            def run(cmd, **kwargs):
                calls.append(list(cmd))
                return domain(cmd, **kwargs)

            # _patch_attrs owns the seam mirroring onto _svc and the shortened
            # settle windows; this local domain is separate from its singleton.
            _patch_attrs(self, run=run,
                         health=lambda state, timeout=20: {'status': 'ok'})
            served = install_mod._svc.ensure_serving(
                501, Path(tmp), {'port': 1, 'token': 't'}, agents=_agents(tmp))
            self.assertTrue(served)
            self.assertTrue([c for c in calls if c[1] == 'bootstrap'],
                            'an unloaded job must be bootstrapped, not just TERMed')
            self.assertTrue(domain.loaded(LABEL))



class SupervisorLogRotationTests(unittest.TestCase):
    """Bounded retention for supervisor-captured logs (Plan 058 Stage 5a).

    router.jsonl already rotates via RotatingFileHandler; launchd.log and
    update.log were unbounded supervisor sinks. rotate_log bounds them with
    rotate-on-start semantics without losing the newest startup failures.
    """

    def _service(self):
        return _load('router_service_rotate_under_test', 'service.py')

    def test_under_limit_log_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'update.log'
            target.write_bytes(b'x' * 100)
            self._service().rotate_log(target, limit_bytes=1024, backups=2)
            self.assertEqual(target.read_bytes(), b'x' * 100)
            self.assertFalse(Path(str(target) + '.1').exists())

    def test_missing_log_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'missing.log'
            self._service().rotate_log(target, limit_bytes=10, backups=2)
            self.assertFalse(target.exists())

    def test_over_limit_log_rotates_keeping_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'launchd.log'
            target.write_bytes(b'new-failure-traceback')
            first = Path(str(target) + '.1')
            first.write_bytes(b'older-output')
            self._service().rotate_log(target, limit_bytes=10, backups=2)
            self.assertEqual(Path(str(target) + '.2').read_bytes(), b'older-output')
            self.assertEqual(first.read_bytes(), b'new-failure-traceback')
            self.assertEqual(target.read_bytes(), b'')


if __name__ == '__main__':
    unittest.main()
