"""Prototypes plugin manifest and registry contracts."""
import importlib.util
import hashlib
import json
import re
import sys
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/scg-prototypes/skills/publish-prototype/scripts/prototypes.py"
spec = importlib.util.spec_from_file_location("scg_prototypes", SCRIPT)
prototypes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prototypes)

CONFIG = {
    "account": "852138521410",
    "archiveRepository": "software-combined/SC_Prototypes",
    "bucket": "scg-prototypes-852138521410",
    "distributionId": "E1234567890ABC",
    "domain": "prototypes.softwarecombined.com",
    "expiryDays": 30,
    "profile": "scg-prototypes",
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


class PrototypeManifestTest(unittest.TestCase):
    def test_marketplace_entry_and_skill_links_resolve_inside_the_plugin(self):
        plugin = ROOT / "plugins/scg-prototypes"
        marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        entries = {entry["name"]: entry for entry in marketplace["plugins"]}
        self.assertIn("scg-prototypes", entries)
        self.assertEqual((ROOT / entries["scg-prototypes"]["source"]["path"]).resolve(), plugin)
        manifest = json.loads((plugin / ".codex-plugin/plugin.json").read_text())
        self.assertEqual(manifest["name"], "scg-prototypes")
        self.assertEqual(manifest["repository"], "https://github.com/software-combined/SC_OpenRouter_adapter")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+(?:\+[A-Za-z0-9.-]+)?$")
        self.assertTrue((plugin / "skills/publish-prototype/SKILL.md").is_file())
        for markdown in (plugin / "skills").glob("*/SKILL.md"):
            for target in re.findall(r"\]\(([^)]+)\)", markdown.read_text()):
                path = target.split("#")[0]
                if path and "://" not in path:
                    resolved = (markdown.parent / path).resolve()
                    self.assertTrue(resolved.is_relative_to(plugin), target)
                    self.assertTrue(resolved.is_file(), target)

    def test_channel_config_matches_the_deployed_channel_contract(self):
        config = json.loads((ROOT / "plugins/scg-prototypes/skills/publish-prototype/references/channel.json").read_text())
        self.assertEqual(config["account"], "852138521410")
        self.assertEqual(config["bucket"], "scg-prototypes-852138521410")
        self.assertEqual(config["domain"], "prototypes.softwarecombined.com")
        self.assertEqual(config["archiveRepository"], "software-combined/SC_Prototypes")
        self.assertEqual(config["expiryDays"], 30)
        self.assertEqual(config["profile"], "scg-prototypes")
        self.assertTrue(
            config["distributionId"] == "" or re.fullmatch(r"E[A-Z0-9]+", config["distributionId"]),
        )


class PrototypeOpsManifestTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.site = self.root / "checkout-v2"
        (self.site / "assets").mkdir(parents=True)
        (self.site / "index.html").write_text('<!doctype html><link rel="stylesheet" href="assets/app.css"><h1>checkout</h1>\n')
        (self.site / "assets" / "app.css").write_text("body{color:#111}\n")
        self.repo = self.root / "SC_Prototypes"
        (self.repo / ".git").mkdir(parents=True)
        self.previous_pin_path = prototypes.GITLEAKS_PIN_PATH
        prototypes.GITLEAKS_PIN_PATH = self.root / "hook-config.json"
        prototypes.GITLEAKS_PIN_PATH.write_text(json.dumps({
            "gitleaks": {"binary": sys.executable, "sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()},
        }))
        self.addCleanup(self.restore_pin_path)

    def restore_pin_path(self):
        prototypes.GITLEAKS_PIN_PATH = self.previous_pin_path

    def test_unpublish_dry_run_keeps_the_archive_and_registry(self):
        prototypes.save_registry(self.repo, {"prototypes": {"checkout-v2-7f3a": prototypes.entry_for(
            "checkout-v2-7f3a", "Checkout v2", CONFIG, datetime.now(timezone.utc), "brent",
        )}})
        printed = []
        prototypes.unpublish(
            arguments(slug="checkout-v2-7f3a", repo_dir=str(self.repo), dry_run=True),
            CONFIG,
            run=RecordingRunner(),
            out=printed.append,
        )
        self.assertIn("checkout-v2-7f3a", printed[0])
        self.assertIn("checkout-v2-7f3a", prototypes.load_registry(self.repo)["prototypes"])

    def test_unpublish_deletes_only_the_slug_prefix_and_keeps_the_archive(self):
        prototypes.save_registry(self.repo, {"prototypes": {"checkout-v2-7f3a": prototypes.entry_for(
            "checkout-v2-7f3a", "Checkout v2", CONFIG, datetime.now(timezone.utc), "brent",
        )}})
        archive = self.repo / "prototypes" / "checkout-v2-7f3a" / "site"
        archive.mkdir(parents=True)
        (archive / "index.html").write_text("archived\n")

        runner = RecordingRunner()
        prototypes.unpublish(
            arguments(slug="checkout-v2-7f3a", repo_dir=str(self.repo), dry_run=False),
            CONFIG,
            run=runner,
            out=lambda _line: None,
        )
        commands = runner.joined()
        delete_index = next(index for index, command in enumerate(commands) if command.startswith(
            "aws s3 rm --recursive s3://scg-prototypes-852138521410/prototypes/checkout-v2-7f3a/",
        ))
        invalidation_index = next(index for index, command in enumerate(commands) if "create-invalidation" in command and "/checkout-v2-7f3a/*" in command)
        push_index = next(index for index, command in enumerate(commands) if command.endswith("push") and "git -C" in command)
        self.assertLess(delete_index, push_index)
        self.assertLess(invalidation_index, push_index)
        self.assertTrue((archive / "index.html").is_file(), "the archived source survives an unpublish")
        self.assertNotIn("checkout-v2-7f3a", prototypes.load_registry(self.repo)["prototypes"])
        self.assertFalse(any("--all" in command for command in commands))

    def test_list_reports_expired_entries(self):
        moment = datetime(2026, 9, 12, tzinfo=timezone.utc)
        prototypes.save_registry(self.repo, {"prototypes": {
            "fresh-0001": prototypes.entry_for("fresh-0001", "Fresh", CONFIG, moment, "brent"),
            "stale-0001": prototypes.entry_for("stale-0001", "Stale", CONFIG, moment - timedelta(days=40), "brent"),
        }})
        printed = []
        rows = prototypes.list_prototypes(arguments(repo_dir=str(self.repo)), CONFIG, out=printed.append, now=moment)
        statuses = {row["slug"]: row["status"] for row in rows}
        self.assertEqual(statuses, {"fresh-0001": "active", "stale-0001": "expired"})
        self.assertTrue(any("stale-0001" in line and "expired" in line for line in printed))


if __name__ == "__main__":
    unittest.main()
