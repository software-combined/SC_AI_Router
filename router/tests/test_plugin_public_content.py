"""Public plugin packages and metadata omit private environment details."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SURFACES = {
    "scg-openrouter": (
        ROOT.parent / ".codex-plugin",
        ROOT.parent / ".claude-plugin",
        ROOT.parent / "skills/manage-router",
    ),
    **{
        entry['name']: (ROOT.parent / entry['source']['path'],)
        for entry in json.loads(
            (ROOT.parent / '.agents/plugins/marketplace.json').read_text())['plugins']
    },
}
PUBLIC_METADATA = (
    ROOT.parent / "AGENTS.md",
    ROOT.parent / ".github/ISSUE_TEMPLATE/config.yml",
    ROOT.parent / ".mailmap",
    ROOT / "README.md",
    ROOT.parent / "SECURITY.md",
    ROOT / "pyproject.toml",
)
SYNTHETIC_EMAIL_FIXTURES = (
    ROOT / "tests/test_download_exchange.py",
    ROOT / "tests/test_provision_key.py",
)
ACCOUNT_ID = re.compile(r"(?<![A-Za-z0-9.])\d{12}(?![A-Za-z0-9.])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
LOCAL_USER_PATH = re.compile(
    r"(?:/Users|/home)/[A-Za-z0-9._-]+/|[A-Za-z]:\\Users\\[A-Za-z0-9._-]+\\",
    re.IGNORECASE,
)
ALLOWED_EMAILS = {"employee@example.invalid", "git@github.com", "test@example.invalid"}


def public_files():
    """Yield text sources from the plugin surfaces and public metadata."""
    for roots in PLUGIN_SURFACES.values():
        for root in roots:
            for path in (root.rglob("*") if root.is_dir() else (root,)):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    yield path
    yield from PUBLIC_METADATA


class PluginPublicContentTests(unittest.TestCase):
    def test_all_nine_plugin_surfaces_are_covered(self):
        self.assertEqual(len(PLUGIN_SURFACES), 9)
        for name, roots in PLUGIN_SURFACES.items():
            with self.subTest(surface=name):
                self.assertTrue(any(path.exists() for path in roots))

    def test_private_release_configuration_is_masked_before_output(self):
        text = (ROOT.parent / ".github/workflows/release.yml").read_text()
        for name in ('FEED_BUCKET', 'FEED_ROLE', 'FEED_SIGNING_SEED_ARN'):
            with self.subTest(name=name):
                self.assertIn(f'{name}: ${{{{ secrets.{name} }}}}', text)
                self.assertNotIn(f'{name}: ${{{{ vars.{name} }}}}', text)

        credential_steps = text.split(
            'uses: aws-actions/configure-aws-credentials@')[1:]
        self.assertTrue(credential_steps, 'the workflow has no AWS credential step')
        for step in credential_steps:
            with self.subTest(step=step.splitlines()[0]):
                block = step.split('\n      - ', 1)[0]
                self.assertIn('mask-aws-account-id: true', block)

        distribution = text.split(
            '- name: Resolve the feed distribution', 1)[1].split(
                '\n      - ', 1)[0]
        mask = distribution.index('echo "::add-mask::$DIST_ID"')
        export = distribution.index(
            'echo "FEED_DISTRIBUTION_ID=$DIST_ID" >> "$GITHUB_ENV"')
        self.assertLess(mask, export,
                        'the derived distribution id must be masked before export')

    def test_no_concrete_account_identifiers_are_published(self):
        for path in public_files():
            if ACCOUNT_ID.search(path.read_text(errors="ignore")):
                self.fail(str(path.relative_to(ROOT.parent)))

    def test_no_personal_email_addresses_are_published(self):
        for path in (*public_files(), *SYNTHETIC_EMAIL_FIXTURES):
            emails = EMAIL.findall(path.read_text(errors="ignore"))
            if any(email not in ALLOWED_EMAILS for email in emails):
                self.fail(str(path.relative_to(ROOT.parent)))

    def test_no_local_user_paths_are_published(self):
        for path in public_files():
            if LOCAL_USER_PATH.search(path.read_text(errors="ignore")):
                self.fail(str(path.relative_to(ROOT.parent)))


if __name__ == "__main__":
    unittest.main()
