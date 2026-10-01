"""The hook entry points run the interpreter recorded in config.json.

Native Windows gets the receipt gate through the same shared adapter as
macOS/Linux: Git for Windows runs the Bash hooks, and the helper interpreter
is an explicit absolute path. Windows defaults to the runtime shipped by the
SCG router and never searches PATH; a POSIX install that predates the setting
keeps the historical python3. Everything here stays in a temp directory.
"""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace


TESTS = Path(__file__).resolve().parent
HOOKS = TESTS.parent
SETUP = HOOKS.parents[1] / "scripts" / "setup.py"
SHIMS = ("pre-commit", "commit-msg", "bin/scg-review-state")


def find_bash():
    """Bash for the shim tests: PATH, else Git for Windows' own copy.

    The Windows runner may keep Git off PATH; without this the whole shim
    class would skip silently and the cross-platform claim would be untested.
    """
    found = shutil.which("bash")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432")):
        if base:
            candidate = Path(base) / "Git" / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
    return None


BASH = find_bash()
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def load_setup():
    spec = importlib.util.spec_from_file_location("review_setup", SETUP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup = load_setup()


class InterpreterSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_windows_default_is_the_router_runtime(self) -> None:
        router = self.base / "router"
        with mock.patch.dict(os.environ, {"ROUTER_HOME": str(router)}):
            resolved = setup.resolve_interpreter({}, "nt")
        self.assertEqual(resolved, str(router / "runtime" / "python" / "python.exe"))

    def test_posix_default_keeps_the_historical_python3(self) -> None:
        self.assertEqual(setup.resolve_interpreter({}, "posix"), "python3")

    def test_an_explicit_interpreter_wins_on_every_platform(self) -> None:
        configured = str(self.base / "python")
        for name in ("nt", "posix"):
            with self.subTest(os_name=name):
                self.assertEqual(
                    setup.resolve_interpreter({"interpreter": configured}, name),
                    configured)

    def test_effective_config_records_only_an_absolute_interpreter(self) -> None:
        self.assertNotIn("interpreter", setup.effective_config({}, "posix"))
        stored = setup.effective_config({}, "nt")
        self.assertEqual(stored["interpreter"],
                         setup.resolve_interpreter({}, "nt"))

    def test_verify_config_rejects_a_relative_interpreter(self) -> None:
        config = {"required_lanes": setup.LANES, "review_state_ttl_seconds": 60,
                  "interpreter": "python3"}
        with self.assertRaisesRegex(ValueError, "absolute path"):
            setup.verify_config(config, "posix")

    def test_verify_config_fails_closed_when_the_windows_runtime_is_absent(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTER_HOME": str(self.base / "missing")}):
            with self.assertRaisesRegex(ValueError, "interpreter is missing"):
                setup.verify_config(
                    {"required_lanes": setup.LANES, "review_state_ttl_seconds": 60},
                    "nt")

    def test_posix_config_without_the_setting_never_probes_an_interpreter(self) -> None:
        # No interpreter key and no probe: the historical contract stands.
        scanner = self.base / "gitleaks"
        scanner.write_bytes(b"stub")
        scanner.chmod(0o755)
        config = {"required_lanes": setup.LANES, "review_state_ttl_seconds": 60,
                  "gitleaks": {"binary": str(scanner), "version": "9.9.9",
                               "sha256": hashlib.sha256(b"stub").hexdigest(),
                               "provenance": "test fixture"}}
        version_probe = SimpleNamespace(returncode=0, stdout="9.9.9\n", stderr="")
        with mock.patch.object(setup, "verify_interpreter") as probe, \
                mock.patch.object(setup.subprocess, "run", return_value=version_probe):
            setup.verify_config(config, "posix")
        probe.assert_not_called()

    @unittest.skipUnless(BASH, "needs Bash to run the installed shim")
    @unittest.skipIf(os.name == "nt", "needs a POSIX scanner stub and interpreter symlink")
    def test_installed_non_ascii_interpreter_path_runs(self) -> None:
        home = self.base / "home"
        repo = self.base / "repo"
        interpreter = self.base / "Jos\u00e9" / "python"
        interpreter.parent.mkdir()
        interpreter.symlink_to(sys.executable)
        scanner = self.base / "gitleaks"
        scanner.write_text("#!/bin/sh\necho 9.9.9\n", encoding="utf-8")
        scanner.chmod(0o755)
        config = {
            "required_lanes": setup.LANES, "review_state_ttl_seconds": 60,
            "interpreter": str(interpreter),
            "gitleaks": {"binary": str(scanner), "version": "9.9.9",
                         "sha256": hashlib.sha256(scanner.read_bytes()).hexdigest(),
                         "provenance": "synthetic test fixture"}}
        environment = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
        subprocess.run(["git", "init", "-b", "main", str(repo)], env=environment,
                       capture_output=True, text=True, check=True)
        with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
            setup.provision(repo, config, install=True, home=home)
            setup.provision(repo, config, home=home)
        done = subprocess.run(
            [BASH, str(HOOKS / "bin/scg-review-state"), "status"], cwd=repo,
            env=environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Review state: none", done.stdout)


@unittest.skipUnless(BASH, "needs a Bash to run the hook shims")
class ShimTest(unittest.TestCase):
    """Run the real shims against a redirected HOME and a stub helper."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        adapter = self.home / ".config" / "scg-agent-git-hooks"
        (adapter / "lib").mkdir(parents=True)
        self.marker = self.base / "argv.txt"
        (adapter / "lib" / "scg_agent_git_hooks.py").write_text(
            "import pathlib, sys\n"
            f"pathlib.Path({str(self.marker)!r}).write_text(' '.join(sys.argv[1:]))\n")
        self.config = adapter / "config.json"
        self.config.write_text(json.dumps(
            {"required_lanes": setup.LANES, "review_state_ttl_seconds": 60,
             "interpreter": sys.executable}))

    def run_shim(self, shim: str, *args: str, env=None) -> subprocess.CompletedProcess:
        environment = {**os.environ, "HOME": str(self.home),
                       "USERPROFILE": str(self.home), **(env or {})}
        return subprocess.run([BASH, str(HOOKS / shim), *args], env=environment,
                              capture_output=True, text=True, timeout=60, check=False)

    def test_each_shim_runs_the_configured_interpreter(self) -> None:
        for shim in SHIMS:
            with self.subTest(shim=shim):
                self.marker.unlink(missing_ok=True)
                done = self.run_shim(shim, "extra")
                self.assertEqual(done.returncode, 0, done.stderr)
                recorded = self.marker.read_text()
                self.assertIn("extra", recorded)
                if shim != "bin/scg-review-state":
                    self.assertIn(shim, recorded)

    def test_the_configured_path_wins_over_a_path_python3(self) -> None:
        # A decoy python3 first on PATH must not be chosen.
        decoy = self.base / "bin"
        decoy.mkdir()
        (decoy / "python3").write_text(f"#!/bin/sh\ntouch {self.base}/decoy\n")
        (decoy / "python3").chmod(0o755)
        done = self.run_shim("pre-commit", env={"PATH": f"{decoy}{os.pathsep}{os.environ['PATH']}"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(self.marker.exists())
        self.assertFalse((self.base / "decoy").exists())

    @unittest.skipIf(os.name == "nt", "no python3 on a native Windows PATH")
    def test_posix_shim_keeps_python3_when_the_setting_is_absent(self) -> None:
        self.config.write_text(json.dumps(
            {"required_lanes": setup.LANES, "review_state_ttl_seconds": 60}))
        decoy = self.base / "bin"
        decoy.mkdir()
        (decoy / "python3").write_text(f"#!/bin/sh\ntouch {self.base}/decoy\n")
        (decoy / "python3").chmod(0o755)
        done = self.run_shim("pre-commit", env={"PATH": f"{decoy}{os.pathsep}{os.environ['PATH']}"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.base / "decoy").exists())


@unittest.skipUnless(POWERSHELL, "needs PowerShell to parse its setup examples")
class SetupInstructionsTest(unittest.TestCase):
    def test_powershell_setup_examples_parse(self) -> None:
        parser = (
            "$tokens = $null; $errors = $null; "
            "[System.Management.Automation.Language.Parser]::ParseInput("
            "[Console]::In.ReadToEnd(), [ref]$tokens, [ref]$errors) | Out-Null; "
            "$errors | ForEach-Object { $_.Message }; "
            "if ($errors.Count) { exit 1 }")
        plugin = SETUP.parents[1]
        for relative in ("references/setup.md", "skills/pre-commit-review/SKILL.md"):
            source = (plugin / relative).read_text(encoding="utf-8")
            blocks = re.findall(r"```powershell\r?\n(.*?)\r?\n```", source, re.S)
            self.assertTrue(blocks, relative)
            for index, block in enumerate(blocks):
                with self.subTest(path=relative, block=index):
                    result = subprocess.run(
                        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", parser],
                        input=block, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
