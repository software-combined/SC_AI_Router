import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/scg-review"
spec = importlib.util.spec_from_file_location("review_setup", PLUGIN / "scripts/setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class PluginTest(unittest.TestCase):
    def test_marketplace_and_bundled_skills_resolve_inside_package(self):
        marketplace = json.loads(
            (ROOT / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
        entry = marketplace["plugins"][0]
        self.assertEqual(marketplace["name"], "scg-agent-plugins")
        self.assertEqual((ROOT / entry["source"]["path"]).resolve(), PLUGIN)
        manifest = json.loads(
            (PLUGIN / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(entry["name"], manifest["name"])
        self.assertEqual(manifest["repository"], "https://github.com/software-combined/SC_AI_Router")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+(?:\+[A-Za-z0-9.-]+)?$")
        for skill in ("pre-commit-review", "code-simplifier", "ponytail", "review-setup"):
            self.assertTrue((PLUGIN / "skills" / skill / "SKILL.md").is_file())
        for markdown in (PLUGIN / "skills").glob("*/SKILL.md"):
            for target in re.findall(r"\]\(([^)]+)\)", markdown.read_text(encoding="utf-8")):
                path = target.split("#")[0]
                if path and "://" not in path:
                    resolved = (markdown.parent / path).resolve()
                    self.assertTrue(resolved.is_relative_to(PLUGIN), target)
                    self.assertTrue(resolved.is_file(), target)

    def test_review_routing_is_one_synchronized_source_with_fixed_efforts(self):
        skills = PLUGIN / "skills"
        review = (skills / "pre-commit-review/SKILL.md").read_text(encoding="utf-8")
        policy_root = ROOT / 'plugins/scg-subagents/skills/optimal-subagents/references'
        canonical = (policy_root / 'reviews.md').read_text(encoding="utf-8")
        self.assertEqual((PLUGIN / 'references/reviews.md').read_text(encoding="utf-8"), canonical)
        self.assertIn('../../references/reviews.md', review)
        self.assertIn('listed eligible fallback', review)
        self.assertIn('Exact user or project model/effort', review)
        required = re.search(
            r'Local user policy override:.*?`([^`]+)` at `([^`]+)`',
            canonical, re.S)
        self.assertIsNotNone(required)
        self.assertIn(f'`{required.group(1)}` at `{required.group(2)}`', review)
        self.assertIn('no model fallback', review.lower())
        efforts = json.loads(
            (policy_root / 'model-evidence.json').read_text(encoding="utf-8"))['prescribed_efforts']
        for model, effort in re.findall(r'`([^`]+)` at `([^`]+)`', canonical):
            self.assertEqual(efforts[model], effort)
        for lane in ('Simplification', 'Correctness', 'Quality', 'Adversarial'):
            self.assertEqual(canonical.count('| ' + lane + ' |'), 1)
        self.assertNotRegex(review, r"muse-spark|glm-5\.3")
        for markdown in skills.glob("*/SKILL.md"):
            self.assertNotRegex(markdown.read_text(encoding="utf-8").lower(), r"kimi|luna")

    def test_review_brief_pins_inspect_commands(self):
        review = (PLUGIN / "skills/pre-commit-review/SKILL.md").read_text(encoding="utf-8")
        for command in (
            "git write-tree",
            "git diff --cached --stat",
            "git diff --cached",
            "git show :path",
        ):
            self.assertIn(command, review)
        self.assertIn("Do not reconstruct trees", review)
        self.assertIn("same model with the same brief", review)
        self.assertNotRegex(review, r"muse-spark|glm-5\.3")

    def test_simplification_wait_guidance_prevents_duplicate_passes(self):
        review = (PLUGIN / "skills/pre-commit-review/SKILL.md").read_text()
        simplifier = (PLUGIN / "skills/code-simplifier/SKILL.md").read_text()
        tool_guide = (ROOT / "plugins/scg-subagents/skills/optimal-subagents/references/tool-guide.md").read_text()
        for text in (review, simplifier, tool_guide):
            self.assertIn("quiet", text.lower())
            self.assertIn("duplicate", text)
            self.assertIn("runtime/transport timeout", text)
        self.assertIn("often the slowest", review)
        self.assertIn("do not cancel, interrupt, respawn", review)
        self.assertIn("Do not cancel or\nrestart an active simplifier", simplifier)

    def test_lane_verdicts_keep_their_label_and_emoji_in_every_relay(self):
        review = (PLUGIN / "skills/pre-commit-review/SKILL.md").read_text()
        for verdict in ("`✅ All Clear`", "`📝 Proceed With Notes`", "`❌ Block`"):
            self.assertIn(verdict, review)
        self.assertIn("whole verdict vocabulary", review)
        self.assertIn("interim update", review)
        self.assertIn("from the first mention, not only in the recap", review)
        self.assertIn("never paraphrased", review)

    def test_shared_updater_and_update_guide_are_synchronized_copies(self):
        marketplace = json.loads(
            (ROOT / '.agents/plugins/marketplace.json').read_text(encoding="utf-8"))
        for entry in marketplace['plugins']:
            plugin = ROOT / entry['source']['path']
            for name in ('updater.py', 'scheduling.py'):
                self.assertEqual((plugin / 'scripts' / name).read_bytes(),
                                 (PLUGIN / 'scripts' / name).read_bytes())
            for skill in (plugin / 'skills').glob('*/SKILL.md'):
                self.assertIn('updates.md', skill.read_text(encoding="utf-8"), str(skill))
        subagents = ROOT / "plugins/scg-subagents"
        self.assertEqual(
            (subagents / "skills/optimal-subagents/references/updates.md").read_bytes(),
            (PLUGIN / "references/updates.md").read_bytes())

    def test_every_marketplace_plugin_ships_matching_dual_manifests(self):
        marketplace = json.loads(
            (ROOT / '.agents/plugins/marketplace.json').read_text(encoding="utf-8"))
        for entry in marketplace['plugins']:
            plugin = ROOT / entry['source']['path']
            with self.subTest(plugin=entry['name']):
                codex = json.loads(
                    (plugin / '.codex-plugin/plugin.json').read_text(encoding="utf-8"))
                claude = json.loads(
                    (plugin / '.claude-plugin/plugin.json').read_text(encoding="utf-8"))
                self.assertEqual(codex['name'], entry['name'])
                self.assertEqual(claude['name'], codex['name'])
                self.assertEqual(claude['version'], codex['version'])

    @unittest.skipIf(os.name == 'nt',
                     'execs a /bin/sh scanner stub and installs a POSIX git '
                     'hook; the hook path itself is exercised on macOS/Linux')
    def test_provision_preserves_existing_configuration_and_requires_matching_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home, repo = base / "home", base / "repo"
            repo.mkdir()
            scanner = base / "scanner"
            marker = base / "scanner-ran"
            scanner.write_text(f'#!/bin/sh\ntouch "{marker}"\necho 8.30.1\n')
            scanner.chmod(0o755)
            config = {"review_state_ttl_seconds": 86400, "required_lanes": setup.LANES,
                      "gitleaks": {"binary": str(scanner), "version": "8.30.1",
                                   "sha256": hashlib.sha256(scanner.read_bytes()).hexdigest(),
                                   "provenance": "test fixture"}}
            with patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}):
                subprocess.run(["git", "init", "-q", str(repo)], check=True)
                bad = {**config, "gitleaks": {**config["gitleaks"], "sha256": "0" * 64}}
                with self.assertRaisesRegex(ValueError, "checksum"):
                    setup.provision(repo, bad, install=True, home=home)
                self.assertFalse(marker.exists(), "Untrusted executable must not run")
                self.assertFalse((home / ".config/scg-agent-git-hooks").exists())
                setup.provision(repo, config, install=True, home=home)
                setup.provision(repo, config, home=home)
                target = home / ".config/scg-agent-git-hooks"
                before = (target / "config.json").read_bytes()
                changed = {**config, "review_state_ttl_seconds": 100}
                with self.assertRaisesRegex(ValueError, "configuration differs"):
                    setup.provision(repo, changed, install=True, home=home)
                self.assertEqual((target / "config.json").read_bytes(), before)
                hook = target / "pre-commit"
                hook.write_text("user-owned hook\n")
                with self.assertRaisesRegex(ValueError, "adapter differs"):
                    setup.provision(repo, config, install=True, home=home)
                self.assertEqual(hook.read_text(), "user-owned hook\n")
                subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", "/user/hooks"], check=True)
                with self.assertRaisesRegex(ValueError, "different core.hooksPath"):
                    setup.provision(repo, config, install=True, home=home)


if __name__ == "__main__":
    unittest.main()
