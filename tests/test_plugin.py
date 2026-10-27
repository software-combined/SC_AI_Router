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
PLUGIN = ROOT / "plugins/development/scg-review"
spec = importlib.util.spec_from_file_location("review_setup", PLUGIN / "scripts/setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class PluginTest(unittest.TestCase):
    def test_ponytail_replaces_the_review_copy_and_installs_first_in_both_clients(self):
        from tests.test_agent_skills_delivery import _Client, _found, skills

        with tempfile.TemporaryDirectory() as temporary:
            self.enterContext(patch.object(Path, 'home', return_value=Path(temporary) / 'home'))
            self.enterContext(patch.dict(os.environ, {'XDG_CONFIG_HOME': ''}))
            root = skills.marketplace_root(Path(temporary))
            old = root / 'plugins/scg-review/skills/ponytail/SKILL.md'
            old.parent.mkdir(parents=True)
            old.write_text('previous bundled skill')
            (root / skills.MARKER).write_text('router-owned fixture')
            names = skills.write_marketplace(root, ROOT / 'plugins')
            self.assertIn('scg-ponytail', names)
            self.assertFalse(old.exists())
            source = ROOT / 'plugins/development/scg-ponytail/skills/ponytail/SKILL.md'
            delivered = root / 'plugins/scg-ponytail/skills/ponytail/SKILL.md'
            self.assertEqual(delivered.read_bytes(), source.read_bytes())
            self.assertEqual(list((root / 'plugins').glob('*/skills/ponytail/SKILL.md')),
                             [delivered])
            for client, verb, manifest in (
                    ('codex', 'add', '.agents/plugins/marketplace.json'),
                    ('claude', 'install', '.claude-plugin/marketplace.json')):
                with self.subTest(client=client):
                    entries = json.loads((root / manifest).read_text(encoding='utf-8'))['plugins']
                    self.assertEqual([p['name'] for p in entries].count('scg-ponytail'), 1)
                    run = _Client()
                    _, refused = skills.register(client, root, names, run=run, which=_found)
                    self.assertEqual(refused, 0)
                    ponytail = [client, 'plugin', verb, 'scg-ponytail@scg-agent-plugins']
                    review = [client, 'plugin', verb, 'scg-review@scg-agent-plugins']
                    self.assertLess(run.calls.index(ponytail), run.calls.index(review))

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
        for skill in ("pre-commit-review", "code-simplifier", "review-setup", "security-review"):
            self.assertTrue((PLUGIN / "skills" / skill / "SKILL.md").is_file())
        self.assertFalse((PLUGIN / "skills/ponytail").exists())
        for markdown in (PLUGIN / "skills").glob("*/SKILL.md"):
            for target in re.findall(r"\]\(([^)]+)\)", markdown.read_text(encoding="utf-8")):
                path = target.split("#")[0]
                if path and "://" not in path:
                    resolved = (markdown.parent / path).resolve()
                    self.assertTrue(resolved.is_relative_to(PLUGIN), target)
                    self.assertTrue(resolved.is_file(), target)

    def test_review_routing_has_one_synchronized_source(self):
        skills = PLUGIN / "skills"
        review = (skills / "pre-commit-review/SKILL.md").read_text(encoding="utf-8")
        policy_root = ROOT / 'plugins/agents/scg-subagents/skills/optimal-subagents/references'
        canonical = (policy_root / 'reviews.md').read_text(encoding="utf-8")
        self.assertEqual((PLUGIN / 'references/reviews.md').read_text(encoding="utf-8"), canonical)
        self.assertIn('../../references/reviews.md', review)
        self.assertIn('Exact user or project model/effort', review)

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

    def test_simplification_wait_guidance_prevents_duplicate_passes(self):
        review = (PLUGIN / "skills/pre-commit-review/SKILL.md").read_text(encoding='utf-8')
        simplifier = (PLUGIN / "skills/code-simplifier/SKILL.md").read_text(encoding='utf-8')
        tool_guide = (ROOT / "plugins/agents/scg-subagents/skills/optimal-subagents/references/tool-guide.md").read_text(encoding='utf-8')
        for text in (review, simplifier, tool_guide):
            self.assertIn("quiet", text.lower())
            self.assertIn("duplicate", text)
            self.assertIn("runtime/transport timeout", text)
        self.assertIn("often the slowest", review)
        self.assertIn("do not cancel, interrupt, respawn", review)
        self.assertIn("Do not cancel or\nrestart an active simplifier", simplifier)

    def test_lane_verdicts_keep_their_label_and_emoji_in_every_relay(self):
        review = (PLUGIN / "skills/pre-commit-review/SKILL.md").read_text(encoding='utf-8')
        for verdict in ("`✅ All Clear`", "`📝 Proceed With Notes`", "`❌ Block`"):
            self.assertIn(verdict, review)
        self.assertIn("whole verdict vocabulary", review)
        self.assertIn("interim update", review)
        self.assertIn("from the first mention, not only in the recap", review)
        self.assertIn("never paraphrased", review)

    def test_posix_interpreter_setting_is_additive(self):
        # A POSIX config that predates the setting keeps the historical bare
        # python3 and is not rewritten, so existing installs still pass check.
        self.assertEqual(setup.resolve_interpreter({}, "posix"), "python3")
        self.assertNotIn("interpreter", setup.effective_config({}, "posix"))

    def test_windows_interpreter_defaults_to_the_router_runtime(self):
        # Windows has no python3 on PATH, so the default is the router's
        # pinned runtime, never a PATH search.
        router = Path("C:/router") if os.name == "nt" else Path("/router")
        with patch.dict(os.environ, {"ROUTER_HOME": str(router)}):
            self.assertEqual(
                setup.resolve_interpreter({}, "nt"),
                str(router / "runtime" / "python" / "python.exe"))

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
        subagents = ROOT / "plugins/agents/scg-subagents"
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
                # A POSIX install records no interpreter, so the installed
                # config is exactly the bytes the owner supplied.
                self.assertEqual((target / "config.json").read_bytes(),
                                 (json.dumps(config, indent=2) + "\n").encode())
                before = (target / "config.json").read_bytes()
                changed = {**config, "review_state_ttl_seconds": 100}
                with self.assertRaisesRegex(ValueError, "configuration differs"):
                    setup.provision(repo, changed, install=True, home=home)
                self.assertEqual((target / "config.json").read_bytes(), before)
                hook = target / "pre-commit"
                hook.write_text("user-owned hook\n")
                with self.assertRaisesRegex(ValueError, "adapter differs"):
                    setup.provision(repo, config, install=True, home=home)
                self.assertEqual(hook.read_text(encoding='utf-8'), "user-owned hook\n")
                subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", "/user/hooks"], check=True)
                with self.assertRaisesRegex(ValueError, "different core.hooksPath"):
                    setup.provision(repo, config, install=True, home=home)


if __name__ == "__main__":
    unittest.main()
