"""Prototypes plugin publish contracts."""
import importlib.util
import hashlib
import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# POSIX fcntl locks the registry in the publish script; it cannot import on
# Windows. The publish path runs on macOS/Linux release hosts. Import it only
# on POSIX; on Windows the classes below are skipped via the ``load_tests``
# hook, so the fcntl-dependent script is never touched. A module-level
# ``raise SkipTest`` would surface as a collection ERROR, not a clean skip.
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT.parent / "plugins/development/scg-prototypes/skills/publish-prototype/scripts/prototypes.py"
if os.name == 'nt':
    prototypes = None
else:
    spec = importlib.util.spec_from_file_location("scg_prototypes", SCRIPT)
    prototypes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prototypes)


def load_tests(loader, tests, pattern):
    """Skip this module cleanly on Windows (see the note above)."""
    if os.name == 'nt':
        return unittest.TestSuite()
    return tests

CONFIG = {
    "account": "000000000000",
    "archiveRepository": "example/prototype-archive",
    "bucket": "synthetic-prototype-bucket",
    "distributionId": "ESYNTHETIC000000",
    "domain": "prototypes.example.invalid",
    "expiryDays": 30,
    "profile": "synthetic-prototypes",
}
class RecordingRunner:
    def __init__(self, status=" M prototypes.json\n"):
        self.commands = []
        self.status = status

    def __call__(self, args, cwd=None):
        self.commands.append([str(item) for item in args])
        if "sts" in args:
            return json.dumps({"Account": CONFIG["account"]})
        if "status" in args and "--porcelain" in args:
            return self.status
        return ""

    def joined(self):
        return [" ".join(command) for command in self.commands]


def arguments(**overrides):
    values = {
        "directory": None,
        "dry_run": False,
        "repo_dir": None,
        "slug": None,
        "source": None,
        "title": None,
        "update": False,
    }
    values.update(overrides)
    return Namespace(**values)


class PrototypeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.site = self.root / "checkout-v2"
        (self.site / "assets").mkdir(parents=True)
        (self.site / "index.html").write_text('<!doctype html><link rel="stylesheet" href="assets/app.css"><h1>checkout</h1>\n')
        (self.site / "assets" / "app.css").write_text("body{color:#111}\n")
        self.repo = self.root / "prototype-archive"
        (self.repo / ".git").mkdir(parents=True)
        self.previous_pin_path = prototypes.GITLEAKS_PIN_PATH
        prototypes.GITLEAKS_PIN_PATH = self.root / "hook-config.json"
        prototypes.GITLEAKS_PIN_PATH.write_text(json.dumps({
            "gitleaks": {"binary": sys.executable, "sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()},
        }))
        self.addCleanup(self.restore_pin_path)

    def restore_pin_path(self):
        prototypes.GITLEAKS_PIN_PATH = self.previous_pin_path

    def test_slug_rules_are_enforced(self):
        prototypes.validate_slug("checkout-v2-7f3a")
        for invalid in ["Checkout", "ab", "-leading", "trailing-", "with_underscore", "x" * 41]:
            with self.assertRaises(prototypes.ChannelError, msg=invalid):
                prototypes.validate_slug(invalid)

    def test_generated_slug_keeps_a_readable_prefix_and_fits_the_limit(self):
        generated = prototypes.make_slug(self.site)
        self.assertTrue(generated.startswith("checkout-v2-"))
        self.assertEqual(len(generated), len("checkout-v2-") + 4)
        long_name = self.root / ("very-long-prototype-name-that-keeps-going" * 2)
        self.assertLessEqual(len(prototypes.make_slug(long_name)), 40)
        self.assertEqual(prototypes.make_slug(self.site, "exact-name"), "exact-name")

    def test_root_absolute_references_are_reported_per_file_and_line(self):
        self.assertEqual(prototypes.find_root_absolute_refs(self.site, "checkout-v2-7f3a"), [])
        (self.site / "assets" / "app.css").write_text("body{background:url(/images/bg.png)}\n")
        (self.site / "index.html").write_text(
            '<script src="/assets/app.js"></script>\n<img src="/checkout-v2-7f3a/assets/ok.png">\n',
        )
        findings = prototypes.find_root_absolute_refs(self.site, "checkout-v2-7f3a")
        self.assertEqual(findings, [
            "assets/app.css:1: /images/bg.png",
            "index.html:1: /assets/app.js",
        ])

    def test_srcset_and_import_references_are_checked_without_flagging_relative_paths(self):
        (self.site / "index.html").write_text(
            '<img srcset="img/hero.webp 1x, img/hero@2x.webp 2x">\n'
            '<img srcset="img/other.webp 1x, /rooted/other.webp 2x">\n'
            '<style>@import "styles/print.css";</style>\n'
            '<style>@import "/rooted/print.css";</style>\n',
        )
        findings = prototypes.find_root_absolute_refs(self.site, "checkout-v2-7f3a")
        self.assertEqual(findings, [
            "index.html:2: /rooted/other.webp",
            "index.html:4: /rooted/print.css",
        ])

    def test_gitleaks_gate_refuses_an_environment_supplied_config(self):
        with patch.dict(os.environ, {"GITLEAKS_CONFIG_TOML": "[allowlist]"}):
            with self.assertRaises(prototypes.ChannelError) as error:
                prototypes.gitleaks_binary()
        self.assertIn("GITLEAKS_CONFIG", str(error.exception))

    def test_gitleaks_gate_verifies_the_pinned_binary_hash(self):
        binary = self.root / "fake-gitleaks"
        binary.write_text("#!/bin/sh\n")
        prototypes.GITLEAKS_PIN_PATH.write_text(json.dumps({"gitleaks": {"binary": str(binary), "sha256": "0" * 64}}))
        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.gitleaks_binary()
        self.assertIn("SHA-256", str(error.exception))

        prototypes.GITLEAKS_PIN_PATH.write_text(json.dumps({
            "gitleaks": {"binary": str(binary), "sha256": hashlib.sha256(binary.read_bytes()).hexdigest()},
        }))
        self.assertEqual(prototypes.gitleaks_binary(), str(binary))

    def test_gitleaks_gate_requires_the_review_hook_pin(self):
        prototypes.GITLEAKS_PIN_PATH = self.root / "missing-hook-config.json"
        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.gitleaks_binary()
        self.assertIn("review-setup", str(error.exception))

    def test_publish_rolls_the_registry_back_when_the_sync_fails(self):
        def failing_sync(args, cwd=None):
            joined = " ".join(str(item) for item in args)
            if "sts" in args:
                return json.dumps({"Account": CONFIG["account"]})
            if "status" in args and "--porcelain" in args:
                return " M prototypes.json\n"
            if joined.startswith("aws s3 sync"):
                raise prototypes.ChannelError("simulated transient sync failure")
            return ""

        with self.assertRaises(prototypes.ChannelError):
            prototypes.publish(
                arguments(directory=str(self.site), slug="checkout-v2-7f3a", repo_dir=str(self.repo)),
                CONFIG,
                run=failing_sync,
                verifier=lambda url: "",
                out=lambda _line: None,
            )
        self.assertNotIn("checkout-v2-7f3a", prototypes.load_registry(self.repo)["prototypes"])

    def test_publish_refuses_a_dirty_archive_clone_before_any_s3_call(self):
        runner = RecordingRunner(status=" M prototypes.json\n?? notes.md\n")
        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.publish(
                arguments(directory=str(self.site), slug="checkout-v2-7f3a", repo_dir=str(self.repo)),
                CONFIG,
                run=runner,
                verifier=lambda url: "",
                out=lambda _line: None,
            )
        self.assertIn("unrelated changes", str(error.exception))
        self.assertFalse(any(command[:2] == ["aws", "s3"] or command[:2] == ["aws", "cloudfront"] for command in runner.commands))

    def test_publish_refuses_symbolic_links_that_reach_outside_the_prototype(self):
        outside = self.root / "private-notes.txt"
        outside.write_text("do not publish me\n")
        (self.site / "linked.txt").symlink_to(outside)
        self.assertEqual(prototypes.find_symlinks(self.site), ["linked.txt"])
        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.publish(
                arguments(directory=str(self.site), slug="checkout-v2-7f3a", repo_dir=str(self.repo)),
                CONFIG,
                run=RecordingRunner(),
            )
        self.assertIn("symbolic links are not published", str(error.exception))
        self.assertFalse((self.repo / "prototypes.json").exists())

    def test_registry_entry_records_the_public_url_and_expiry(self):
        published_at = datetime(2026, 9, 12, 10, 30, tzinfo=timezone.utc)
        entry = prototypes.entry_for("checkout-v2-7f3a", "Checkout v2", CONFIG, published_at, "brent")
        self.assertEqual(entry["url"], "https://prototypes.example.invalid/checkout-v2-7f3a/")
        self.assertEqual(entry["expiresAt"], (published_at + timedelta(days=30)).isoformat(timespec="seconds"))
        registry = {"prototypes": {"checkout-v2-7f3a": entry}}
        prototypes.save_registry(self.repo, registry)
        self.assertEqual(prototypes.load_registry(self.repo), registry)
        self.assertEqual(prototypes.load_registry(self.root / "missing"), {"prototypes": {}})

    def test_publish_dry_run_reports_the_plan_without_writing_anything(self):
        runner = RecordingRunner()
        printed = []
        result = prototypes.publish(
            arguments(directory=str(self.site), slug="checkout-v2-7f3a", dry_run=True, repo_dir=str(self.repo)),
            CONFIG,
            run=runner,
            out=printed.append,
        )
        self.assertTrue(result["dryRun"])
        self.assertTrue(all("detect" in command for command in runner.commands), runner.joined())
        self.assertIn("https://prototypes.example.invalid/checkout-v2-7f3a/", " ".join(printed))
        self.assertFalse((self.repo / "prototypes").exists())
        self.assertFalse((self.repo / "prototypes.json").exists())

    def test_publish_archives_the_site_then_syncs_and_invalidates(self):
        runner = RecordingRunner()
        printed = []
        result = prototypes.publish(
            arguments(directory=str(self.site), slug="checkout-v2-7f3a", title="Checkout v2", repo_dir=str(self.repo)),
            CONFIG,
            run=runner,
            verifier=lambda url: "",
            out=printed.append,
        )
        archived = self.repo / "prototypes" / "checkout-v2-7f3a" / "site"
        self.assertTrue((archived / "index.html").is_file())
        self.assertTrue((archived / "assets" / "app.css").is_file())
        self.assertEqual(result["url"], "https://prototypes.example.invalid/checkout-v2-7f3a/")
        registry = json.loads((self.repo / "prototypes.json").read_text())
        self.assertEqual(registry["prototypes"]["checkout-v2-7f3a"]["title"], "Checkout v2")
        commands = runner.joined()
        self.assertTrue(any(command.startswith("git -C") and "commit" in command for command in commands))
        self.assertTrue(any(command.startswith("aws s3 rm --recursive s3://synthetic-prototype-bucket/prototypes/checkout-v2-7f3a/") for command in commands))
        self.assertTrue(any("cloudfront create-invalidation" in command and "/checkout-v2-7f3a/*" in command for command in commands))
        self.assertIn("Published https://prototypes.example.invalid/checkout-v2-7f3a/", printed[-1])

    def test_publish_refuses_an_existing_slug_unless_update_is_requested(self):
        prototypes.save_registry(self.repo, {"prototypes": {"checkout-v2-7f3a": prototypes.entry_for(
            "checkout-v2-7f3a", "Checkout v2", CONFIG, datetime.now(timezone.utc), "brent",
        )}})
        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.publish(
                arguments(directory=str(self.site), slug="checkout-v2-7f3a", repo_dir=str(self.repo)),
                CONFIG,
                run=RecordingRunner(),
                verifier=lambda url: "",
            )
        self.assertIn("already published", str(error.exception))


if __name__ == "__main__":
    unittest.main()
