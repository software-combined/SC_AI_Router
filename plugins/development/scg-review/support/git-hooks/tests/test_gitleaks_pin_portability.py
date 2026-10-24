"""Scanner-path portability and pin integrity, with no scanner execution.

``test_review_gate.py`` now covers the receipt gate on every platform; its two
scanner tests stay POSIX-only because they drive a ``/bin/sh`` stub. The
configured scanner claims native Windows support, so the pin path and the
scanner argv need coverage that runs on every platform. These tests exercise
the helper in-process and stub the subprocess boundary, so nothing is
installed, executed or written outside a temp dir.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


HELPER = Path(__file__).resolve().parents[1] / "lib" / "scg_agent_git_hooks.py"


def load_helper_module():
    spec = importlib.util.spec_from_file_location("scg_agent_git_hooks", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GitleaksPinPortabilityTest(unittest.TestCase):
    class _Completed:
        def __init__(self, stdout: str = "", returncode: int = 0) -> None:
            self.stdout = stdout
            self.stderr = ""
            self.returncode = returncode

    def setUp(self) -> None:
        self.module = load_helper_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.scanner = Path(self.temp.name) / ("gitleaks.exe" if os.name == "nt" else "gitleaks")
        self.scanner.write_bytes(b"pinned-scanner-bytes")
        if os.name == "posix":
            self.scanner.chmod(0o755)
        self.sha256 = hashlib.sha256(self.scanner.read_bytes()).hexdigest()

    def config(self, *, binary=None, version: str = "9.9.9", sha256: str | None = None) -> dict:
        return {
            "review_state_ttl_seconds": 86400,
            "required_lanes": ["correctness", "quality", "adversarial", "security"],
            "gitleaks": {
                "binary": str(self.scanner if binary is None else binary),
                "version": version,
                "sha256": sha256 or self.sha256,
                "timeout_seconds": 10,
            },
        }

    def run_scan(
        self,
        config: dict,
        *,
        env: dict | None = None,
        returncode: int = 0,
        reported_version: str | None = None,
    ) -> list[list[str]]:
        """Run scan() with the git and subprocess boundaries stubbed.

        ``reported_version`` is what the stub scanner prints for ``version``;
        it defaults to the pin's version so the probe passes, and is set to a
        different value to exercise the mismatch path.
        """
        calls: list[list[str]] = []
        reported = config["gitleaks"]["version"] if reported_version is None else reported_version

        def stub_run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[1:2] == ["version"]:
                return self._Completed(stdout=reported + "\n")
            return self._Completed(returncode=returncode)

        info = {
            "repo_root": str(self.repo),
            "repo_id": "test",
            "branch": "main",
            "tree": "test-tree",
            "staged_files": ["file.txt"],
        }
        with mock.patch.object(self.module, "load_config", return_value=config), \
             mock.patch.object(self.module, "repo_info", return_value=info), \
             mock.patch.object(self.module.subprocess, "run", side_effect=stub_run), \
             mock.patch.dict(os.environ, env or {}, clear=False):
            for var in ("GITLEAKS_CONFIG", "GITLEAKS_CONFIG_TOML"):
                if var not in (env or {}):
                    os.environ.pop(var, None)
            self.module.scan(None)
        return calls

    def test_host_native_absolute_binary_path_is_accepted(self) -> None:
        # Reaching the scan at all proves the host-native path passed pin
        # validation; the setUp path is absolute by construction.
        self.run_scan(self.config())

    @unittest.skipUnless(os.name == "posix", "POSIX absolute-path form")
    def test_posix_absolute_binary_path_is_accepted(self) -> None:
        pin = self.module.load_gitleaks_pin(self.config(binary="/usr/local/bin/gitleaks"))
        self.assertEqual(pin["binary"], Path("/usr/local/bin/gitleaks"))

    @unittest.skipUnless(os.name == "nt", "Windows absolute-path form")
    def test_windows_absolute_binary_path_is_accepted(self) -> None:
        pin = self.module.load_gitleaks_pin(self.config(binary=r"C:\Tools\gitleaks\gitleaks.exe"))
        self.assertEqual(pin["binary"], Path(r"C:\Tools\gitleaks\gitleaks.exe"))

    @unittest.skipUnless(os.name == "nt", "Windows drive-relative-path form")
    def test_windows_drive_relative_binary_path_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            self.module.load_gitleaks_pin(self.config(binary=r"\Tools\gitleaks.exe"))

    def test_relative_binary_paths_are_rejected(self) -> None:
        for value in ("gitleaks", "./gitleaks", "../gitleaks", "bin/gitleaks", ""):
            with self.subTest(binary=value):
                with self.assertRaises(SystemExit):
                    self.module.load_gitleaks_pin(self.config(binary=value))

    def test_scan_passes_the_platform_native_null_device(self) -> None:
        scan_cmd = self.run_scan(self.config())[-1]
        index = scan_cmd.index("--gitleaks-ignore-path")
        self.assertEqual(scan_cmd[index + 1], os.devnull)

    def test_scan_still_verifies_the_pinned_sha256(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_scan(self.config(sha256="0" * 64))

    def test_scan_still_verifies_the_pinned_version(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_scan(self.config(), reported_version="1.0.0")

    def test_scan_still_refuses_environment_gitleaks_config(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_scan(self.config(), env={"GITLEAKS_CONFIG": "/tmp/x.toml"})

    def test_scan_still_refuses_repository_gitleaks_config(self) -> None:
        (self.repo / ".gitleaksignore").write_text("fingerprint\n")
        with self.assertRaises(SystemExit):
            self.run_scan(self.config())

    def test_scan_still_blocks_on_a_nonzero_scanner_exit(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_scan(self.config(), returncode=1)


if __name__ == "__main__":
    unittest.main()
