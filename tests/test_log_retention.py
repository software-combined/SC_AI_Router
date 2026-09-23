"""Thirty-day log ageing at every service start and scheduled pass (Plan 178).

The per-file caps bound each log; this bound is the pile. Rotated backups,
old support bundles and task XML age out a month after their last write,
while the three files a live process holds open keep their size caps.
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests.install_fixtures import install_mod

_ROOT = Path(__file__).resolve().parents[1]
_SVC = install_mod._svc
_DAY = 86400
_LIVE = ('router.jsonl', 'launchd.log', 'update.log')


def _aged(path, days=40):
    """Create a file with a last-write stamp old enough to age out."""
    path.write_text('old\n')
    stamp = time.time() - days * _DAY
    os.utime(path, (stamp, stamp))
    return path


class PruneLogsTests(unittest.TestCase):
    def test_old_files_go_and_live_sinks_and_fresh_files_stay(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / 'logs'
            logs.mkdir()
            stale = [_aged(logs / name) for name in
                     ('router.jsonl.1', 'launchd.log.2', 'update.log.1',
                      'support-20260101T000000Z.json', 'CodexMixedModelRouter.task.xml')]
            live = [_aged(logs / name) for name in _LIVE]
            fresh = logs / 'router.jsonl.4'
            fresh.write_text('new\n')
            self.assertEqual(_SVC.prune_logs(logs), len(stale))
            self.assertEqual(sorted(p.name for p in logs.iterdir()),
                             sorted([p.name for p in live] + [fresh.name]))

    def test_missing_directory_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_SVC.prune_logs(Path(tmp) / 'gone'), 0)

    def test_symlink_and_subdirectory_are_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / 'logs'
            logs.mkdir()
            target = _aged(logs / 'router.jsonl.9')
            link = logs / 'link.log'
            link.symlink_to(target)
            os.utime(link, (time.time() - 90 * _DAY,) * 2, follow_symlinks=False)
            nested = logs / 'nested'
            nested.mkdir()
            deep = _aged(nested / 'deep.log')
            self.assertEqual(_SVC.prune_logs(logs), 1)
            self.assertFalse(target.exists())
            self.assertTrue(link.is_symlink())
            self.assertTrue(deep.exists())


class RetentionTriggerTests(unittest.TestCase):
    def _home(self, tmp):
        home = Path(tmp) / 'home'
        (home / 'logs').mkdir(parents=True)
        return home

    def test_router_launcher_prunes_at_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp)
            release = home / 'releases' / '9.9.9'
            release.mkdir(parents=True)
            ignore = shutil.ignore_patterns('__pycache__')
            shutil.copytree(_ROOT / 'packaging', release / 'packaging', ignore=ignore)
            shutil.copytree(_ROOT / 'ai_router', release / 'ai_router', ignore=ignore)
            # The launcher must age the logs and then run the release: a stub
            # entry point keeps the router itself out of this test.
            (release / 'ai_router' / '__main__.py').write_text('raise SystemExit(0)\n')
            (home / 'current').write_text('9.9.9\n')
            shutil.copy(_ROOT / 'packaging' / 'router_launch.py', home / 'router_launch.py')
            stale = _aged(home / 'logs' / 'router.jsonl.1')
            done = subprocess.run([sys.executable, str(home / 'router_launch.py')],
                                  cwd=tmp, capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertFalse(stale.exists(), 'the launcher ages logs at start')

    def test_scheduled_pass_prunes_each_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp)
            stale = _aged(home / 'logs' / 'support-20260101T000000Z.json')
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            with redirect_stdout(io.StringIO()):
                rc = install_mod.do_update(
                    args, _fetch=lambda url: b'',
                    _read_feed=lambda feed, etag: (304, b'', 'etag'),
                    _sleep=lambda seconds: None,
                    _announce=lambda _home, _state: None)
            self.assertEqual(rc, 0)
            self.assertFalse(stale.exists(), 'a scheduled pass ages logs out')


if __name__ == '__main__':
    unittest.main()
