import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "updater", ROOT / "plugins/scg-review/scripts/updater.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)

REVIEW = "scg-review@scg-agent-plugins"
SUBAGENTS = "scg-subagents@scg-agent-plugins"


def entry(plugin_id, version="0.1.0", enabled=True):
    return {"pluginId": plugin_id, "enabled": enabled, "version": version}


def approved_source():
    return {"marketplaces": [{"name": updater.MARKETPLACE,
            "marketplaceSource": {"sourceType": "git",
            "source": "https://github.com/software-combined/SC_AI_Router.git"}}]}


class UpdaterTest(unittest.TestCase):
    def test_one_refresh_reinstalls_every_enabled_plugin_and_verifies_versions(self):
        before = [entry(REVIEW, "0.2.0"), entry(SUBAGENTS, "0.1.1")]
        after = [entry(REVIEW, "0.2.1"), entry(SUBAGENTS, "0.1.2")]
        with patch.object(updater, "cli", side_effect=[
                {"installed": before}, approved_source(), {},
                {"installed": after}, after[0], {"installed": after},
                after[1], {"installed": after}]) as cli:
            message = updater.update("/codex")
        self.assertIn(REVIEW + " 0.2.1", message)
        self.assertIn(SUBAGENTS + " 0.1.2", message)
        calls = cli.call_args_list
        self.assertEqual(sum(1 for c in calls if "upgrade" in c.args), 1)
        self.assertEqual([c.args[3] for c in calls if "add" in c.args], [REVIEW, SUBAGENTS])

    def test_skips_when_nothing_enabled_and_when_plugins_disappear_mid_refresh(self):
        for entries in ([], [entry(REVIEW, enabled=False), entry(SUBAGENTS, enabled=False)]):
            with self.subTest(entries=entries), patch.object(
                    updater, "cli", return_value={"installed": entries}) as cli:
                self.assertIn("Skipped", updater.update("/codex"))
                self.assertEqual(cli.call_count, 1)
        with patch.object(updater, "installed", side_effect=[[entry(REVIEW)], []]), \
                patch.object(updater, "verify_source"), patch.object(updater, "cli") as cli:
            self.assertIn("during refresh", updater.update("/codex"))
            self.assertEqual(cli.call_count, 1)

    def test_plugin_disabled_during_another_install_is_not_reenabled(self):
        both = [entry(REVIEW), entry(SUBAGENTS)]
        remaining = entry(REVIEW, '0.4.0')
        with patch.object(updater, 'cli', side_effect=[
                {'installed': both}, approved_source(), {}, {'installed': both},
                remaining, {'installed': [remaining, entry(SUBAGENTS, enabled=False)]}]) as cli:
            updater.update('/codex')
        self.assertEqual([c.args[3] for c in cli.call_args_list if 'add' in c.args], [REVIEW])

    def test_disabled_plugin_is_not_reinstalled_and_source_is_verified(self):
        enabled = entry(REVIEW, "0.2.1")
        disabled = entry(SUBAGENTS, "0.1.1", enabled=False)
        with patch.object(updater, "cli", side_effect=[
                {"installed": [enabled, disabled]}, approved_source(), {},
                {"installed": [enabled, disabled]},
                enabled, {"installed": [enabled, disabled]}]) as cli:
            message = updater.update("/codex")
        self.assertIn(REVIEW + " 0.2.1", message)
        self.assertNotIn(SUBAGENTS, message)
        self.assertEqual([c.args[3] for c in cli.call_args_list if "add" in c.args], [REVIEW])
        with patch.object(updater, "cli", side_effect=[
                {"installed": [enabled]},
                {"marketplaces": [{"name": updater.MARKETPLACE,
                 "marketplaceSource": {"sourceType": "local", "source": "/elsewhere"}}]}]) as cli:
            with self.assertRaisesRegex(ValueError, "approved"):
                updater.update("/codex")
            self.assertEqual(cli.call_count, 2)

    def test_readback_mismatch_and_refresh_failure_block_install(self):
        with patch.object(updater, "cli", side_effect=[
                {"installed": [entry(REVIEW)]}, approved_source(), {},
                {"installed": [entry(REVIEW)]},
                entry(REVIEW, "9.9.9"), {"installed": [entry(REVIEW)]}]):
            with self.assertRaisesRegex(ValueError, "readback"):
                updater.update("/codex")
        with patch.object(updater, "installed", return_value=[entry(REVIEW)]), \
                patch.object(updater, "verify_source"), patch.object(
                updater, "cli", side_effect=subprocess.CalledProcessError(1, ["codex"])) as cli:
            with self.assertRaises(subprocess.CalledProcessError):
                updater.update("/codex")
            self.assertEqual(cli.call_count, 1)

    def test_cli_is_noninteractive_and_bounded(self):
        with patch.object(updater.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 0, json.dumps({"ok": True}))) as run:
            self.assertTrue(updater.cli("/codex", "plugin", "list")["ok"])
            self.assertEqual(run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(run.call_args.kwargs["timeout"], 120)

    def test_schedule_is_stable_and_refuses_unknown_files(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(updater.Path, "home", return_value=Path(tmp)), \
                patch.object(updater.sys, "platform", "darwin"), \
                patch.object(updater, "installed", return_value=[entry(REVIEW)]), \
                patch.object(updater, "verify_source"), \
                patch.object(updater.subprocess, "run") as run:
            run.side_effect = [subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0)]
            updater.install("/absolute/codex")
            script = Path(tmp) / ".local/share/scg-agent-plugins/updater.py"
            plist = Path(tmp) / "Library/LaunchAgents" / (updater.LABEL + ".plist")
            definition = plistlib.loads(plist.read_bytes())
            self.assertEqual(definition["StartInterval"], 86400)
            self.assertTrue(definition["RunAtLoad"])
            self.assertEqual(definition["ProgramArguments"][1:],
                             [str(script), "run", "--codex", "/absolute/codex"])
            self.assertEqual(script.read_bytes(), Path(updater.__file__).read_bytes())
            self.assertEqual(run.call_args.args[0],
                             ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)])
            run.side_effect = [subprocess.CompletedProcess([], 0)]
            self.assertIn("already configured", updater.install("/absolute/codex"))
            script.write_text("existing user content")
            run.reset_mock()
            with self.assertRaisesRegex(ValueError, "Existing updater files differ"):
                updater.install("/absolute/codex")
            self.assertEqual(script.read_text(), "existing user content")
            run.assert_not_called()

    def test_migration_retires_released_per_plugin_schedulers_once(self):
        digest = lambda text: hashlib.sha256(text).hexdigest()
        legacy = (
            ("com.softwarecombined.agent-plugins.update",
             ".local/share/scg-agent-plugins/updater.py", digest(b"released review updater"), True),
            ("com.softwarecombined.subagents.update",
             ".local/share/scg-subagents/updater.py", digest(b"released subagents updater"), False),
        )
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(updater.Path, "home", return_value=Path(tmp)), \
                patch.object(updater.sys, "platform", "darwin"), \
                patch.object(updater, "installed", return_value=[entry(REVIEW)]), \
                patch.object(updater, "verify_source"), \
                patch.object(updater, "LEGACY", legacy), \
                patch.object(updater.subprocess, "run") as run:
            calls = []

            def fake(cmd, **kwargs):
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 1 if "print" in cmd else 0)

            run.side_effect = fake
            home = Path(tmp)
            review_script = home / ".local/share/scg-agent-plugins/updater.py"
            review_script.parent.mkdir(parents=True)
            review_script.write_bytes(b"released review updater")
            subagents_script = home / ".local/share/scg-subagents/updater.py"
            subagents_script.parent.mkdir(parents=True)
            subagents_script.write_bytes(b"released subagents updater")
            launch_agents = home / "Library/LaunchAgents"
            launch_agents.mkdir(parents=True)
            for label in ("com.softwarecombined.agent-plugins.update",
                          "com.softwarecombined.subagents.update"):
                target = review_script if label == updater.LABEL else subagents_script
                (launch_agents / (label + ".plist")).write_bytes(plistlib.dumps({
                    'ProgramArguments': ['/python', str(target), 'run', '--codex', '/absolute/codex']}))
            message = updater.install("/absolute/codex", migrate=True)
            self.assertIn("Retired earlier schedulers", message)
            self.assertNotEqual(review_script.read_bytes(), b"released review updater")
            self.assertTrue((review_script.parent / "updater.py.migrated").is_file())
            self.assertTrue((subagents_script.parent / "updater.py.migrated").is_file())
            self.assertTrue((launch_agents / (updater.LABEL + ".plist.migrated")).is_file())
            self.assertTrue((launch_agents / "com.softwarecombined.subagents.update.plist.migrated").is_file())
            self.assertFalse((launch_agents / "com.softwarecombined.subagents.update.plist").exists())
            self.assertEqual([c[1] for c in calls if "bootout" in c],
                             ["bootout", "bootout"])
            run.side_effect = None
            run.return_value = subprocess.CompletedProcess([], 0)
            self.assertIn("already configured", updater.install("/absolute/codex"))

    def test_windows_migration_preserves_task_and_files_when_stop_fails(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(updater.Path, 'home', return_value=Path(tmp)), \
                patch.object(updater.sys, 'platform', 'win32'):
            script = Path(tmp) / '.local/share/scg-agent-plugins/updater.py'
            script.parent.mkdir(parents=True)
            script.write_bytes(b'released runner')
            scheduling = updater.scheduler()
            definition = scheduling.windows_xml(Path(updater.sys.executable).with_name('pythonw.exe'),
                                                script, '/codex', 'S-1-5-21')
            exported = script.with_name('update.task.xml')
            exported.write_bytes(definition)
            legacy = ((updater.LABEL, str(script.relative_to(tmp)),
                       hashlib.sha256(script.read_bytes()).hexdigest(), True),)

            def command(args, **kwargs):
                if '/end' in args:
                    if kwargs.get('check'):
                        raise subprocess.CalledProcessError(1, args)
                    return subprocess.CompletedProcess(args, 1)
                return subprocess.CompletedProcess(args, 0, definition)

            with patch.object(updater, 'LEGACY', legacy), \
                    patch.object(scheduling, 'windows_identity', return_value=['account', 'S-1-5-21']), \
                    patch.object(scheduling, 'run', side_effect=command) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    updater.retire_legacy(True, scheduling, '/codex')
            self.assertFalse(any('/delete' in call.args[0] for call in run.call_args_list))
            self.assertEqual(script.read_bytes(), b'released runner')
            self.assertEqual(exported.read_bytes(), definition)
            self.assertFalse(list(script.parent.glob('*.migrated')))

    def test_pre_move_runner_is_accepted_for_migration(self):
        # Digest of the released pre-move updater (SC_Agent_plugins main
        # 5e56a3e), verified against the deployed shared runner before the
        # move. Pinned as a literal so this test runs on shallow checkouts.
        pre_move = "4ded20ea2db5a42c4641ccdbb2845e3f21513644a2d01d5acfa787e77ed9f83a"
        self.assertIn(pre_move, updater.LEGACY[0][2])

    def test_migration_requires_the_explicit_flag_and_verified_content(self):
        digest = hashlib.sha256(b"released review updater").hexdigest()
        legacy = (("com.softwarecombined.agent-plugins.update",
                   ".local/share/scg-agent-plugins/updater.py", digest, True),)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(updater.Path, "home", return_value=Path(tmp)), \
                patch.object(updater.sys, "platform", "darwin"), \
                patch.object(updater, "installed", return_value=[entry(REVIEW)]), \
                patch.object(updater, "verify_source"), \
                patch.object(updater, "LEGACY", legacy), \
                patch.object(updater.subprocess, "run") as run:
            script = Path(tmp) / ".local/share/scg-agent-plugins/updater.py"
            script.parent.mkdir(parents=True)
            script.write_bytes(b"released review updater")
            with self.assertRaisesRegex(ValueError, "--migrate"):
                updater.install("/absolute/codex")
            self.assertEqual(script.read_bytes(), b"released review updater")
            run.assert_not_called()

    def test_migration_resumes_after_interrupt_and_preflights_before_retiring(self):
        legacy = (
            ("com.softwarecombined.agent-plugins.update",
             ".local/share/scg-agent-plugins/updater.py",
             hashlib.sha256(b"released review updater").hexdigest(), True),
            ("com.softwarecombined.subagents.update",
             ".local/share/scg-subagents/updater.py",
             hashlib.sha256(b"released subagents updater").hexdigest(), False),
        )
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(updater.Path, "home", return_value=Path(tmp)), \
                patch.object(updater.sys, "platform", "darwin"), \
                patch.object(updater, "installed", return_value=[entry(REVIEW)]), \
                patch.object(updater, "verify_source"), \
                patch.object(updater, "LEGACY", legacy), \
                patch.object(updater.subprocess, "run") as run:
            calls = []

            def fake(cmd, **kwargs):
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 1 if "print" in cmd else 0)

            run.side_effect = fake
            home = Path(tmp)
            review_script = home / ".local/share/scg-agent-plugins/updater.py"
            review_script.parent.mkdir(parents=True)
            review_script.write_bytes(b"released review updater")
            launch_agents = home / "Library/LaunchAgents"
            launch_agents.mkdir(parents=True)
            # Interrupted migration: the released plist is already relocated
            # while the legacy script and its stopped service remain in place.
            (launch_agents / (updater.LABEL + ".plist.migrated")).write_bytes(b"old plist")
            message = updater.install("/absolute/codex", migrate=True)
            self.assertIn("Retired earlier schedulers", message)
            self.assertNotEqual(review_script.read_bytes(), b"released review updater")
            self.assertTrue((review_script.parent / "updater.py.migrated").is_file())

            # Unknown owned content aborts before any service is touched.
            calls.clear()
            review_script.write_bytes(b"user-owned content")
            subagents_script = home / ".local/share/scg-subagents/updater.py"
            subagents_script.parent.mkdir(parents=True)
            subagents_script.write_bytes(b"released subagents updater")
            subagents_plist = launch_agents / "com.softwarecombined.subagents.update.plist"
            subagents_plist.write_bytes(b"old plist")
            with self.assertRaisesRegex(ValueError, "Existing updater files differ"):
                updater.install("/absolute/codex", migrate=True)
            self.assertEqual(calls, [])
            self.assertEqual(subagents_script.read_bytes(), b"released subagents updater")
            self.assertTrue(subagents_plist.is_file())


if __name__ == "__main__":
    unittest.main()
