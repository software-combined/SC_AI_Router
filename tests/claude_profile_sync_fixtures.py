"""Shared synthetic fixtures for Claude profile session sync tests."""
import base64
import hashlib
import importlib.util
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def fingerprint(root):
    values = []
    for path in sorted(Path(root).rglob('*')):
        if path.is_symlink():
            values.append((path.relative_to(root).as_posix(), 'symlink'))
        elif path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            values.append((path.relative_to(root).as_posix(), digest,
                           stat.S_IMODE(path.stat().st_mode)))
    return tuple(values)


def load_helper(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] /
                                                'packaging' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STORES = ('local-agent-mode-sessions', 'claude-code-sessions')


def profile(root, name, account, organization):
    profile_path = Path(root).resolve() / name
    profile_path.mkdir(parents=True)
    (profile_path / 'config.json').write_text(json.dumps({
        'lastKnownAccountUuid': account,
        'lastKnownOrganizationUuid': organization,
        'accountName': name + ' account',
        'emailAddress': name.lower() + '@example.invalid',
    }))
    if name == 'Claude-3p':
        third_party_identity(profile_path, account, organization)
    return profile_path


def third_party_identity(profile_path, account, organization):
    (profile_path / 'ant-did').write_bytes(base64.b64encode(account.encode()))
    library = profile_path / 'configLibrary'
    library.mkdir(exist_ok=True)
    meta = library / '_meta.json'
    if not meta.exists():
        meta.write_text(json.dumps({'appliedId': '11111111-2222-4333-8444-555555555555'}))
    path = library / (json.loads(meta.read_bytes())['appliedId'] + '.json')
    doc = json.loads(path.read_bytes()) if path.exists() else {
        'inferenceProvider': 'gateway', 'inferenceCredentialKind': 'static',
        'inferenceGatewayApiKey': 'synthetic-key'}
    doc['deploymentOrganizationUuid'] = organization
    path.write_text(json.dumps(doc))


def subscription_identity(profile_path):
    """Simulated native identity boundary; these are not app-owned org fields."""
    try:
        doc = json.loads((Path(profile_path) / 'config.json').read_bytes())
        account, org = doc['lastKnownAccountUuid'], doc['lastKnownOrganizationUuid']
        return (account, org) if isinstance(account, str) and isinstance(org, str) else None
    except (OSError, ValueError, KeyError):
        return None


def namespace(profile_path, store, account, organization):
    if store == 'local-agent-mode-sessions':
        account, organization = account[:8], organization[:8]
    path = Path(profile_path) / store / account / organization
    path.mkdir(parents=True, exist_ok=True)
    return path


class PairFixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.store = self.root / 'store'
        self.ns = self.store / 'account' / 'org'
        self.ns.mkdir(parents=True)
        self.record = self.ns / 'local_same.json'
        self.bundle = self.record.with_suffix('')
        self.stage = self.ns / ('local_same.tmp-' + 'a' * 32)
        self.record.write_text('{"sessionId":"same","title":"old"}')
        (self.bundle / 'outputs').mkdir(parents=True)
        (self.bundle / 'outputs/old.txt').write_text('old')
        (self.stage / 'outputs').mkdir(parents=True)
        (self.stage / 'outputs/new.txt').write_text('new')
        self.text = json.dumps({'sessionId': 'same', 'title': 'new'})
        self.transaction = load_helper('claude_profile_transaction')
        self.publish = self.transaction._publish

    def manifest(self, duplicates=()):
        return self.transaction.write_pair_manifest(
            self.store, self.record, self.bundle, self.text, self.stage,
            duplicates=duplicates)

    def duplicate(self, name='duplicate'):
        path = self.ns / ('local_' + name + '.json')
        path.write_text('{"sessionId":"same","title":"duplicate"}')
        path.with_suffix('').mkdir()
        (path.with_suffix('') / 'unique.txt').write_text('unique')
        return path


def record(profile_path, store, account, organization, session_id, *,
           filename=None, title='task', cli=None, cwd=None, bundle_files=None,
           transcript=None, local_secret=None, mode=None):
    path = namespace(profile_path, store, account, organization) / (
        filename or ('local_' + session_id + '.json'))
    doc = {'sessionId': session_id, 'title': title, 'sourceProfile': 'fixture'}
    if cli:
        doc['cliSessionId'] = cli
    if cwd:
        doc['cwd'] = str(cwd)
    if local_secret:
        doc['targetLocalSecret'] = local_secret
    path.write_text(json.dumps(doc))
    if mode is not None:
        path.chmod(mode)
    bundle = path.with_suffix('')
    if bundle_files is not None or transcript is not None:
        bundle.mkdir(parents=True, exist_ok=True)
        for relative, content in (bundle_files or {}).items():
            artifact = bundle / relative
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(content)
        if transcript is not None:
            artifact = (bundle / '.claude' / 'projects' / 'session' /
                        ((cli or 'fallback') + '.jsonl'))
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps({
                'message': {'content': transcript}}) + '\n')
    return path


def target_only(profile_path, store, account, organization, session_id):
    return record(profile_path, store, account, organization, session_id,
                  title='target-only', bundle_files={'outputs/keep.txt': 'keep'})


def duplicate(profile_path, store, account, organization, session_id, suffix,
              *, title, bundle_files=None):
    return record(profile_path, store, account, organization, session_id,
                  filename='local_' + suffix + '.json', title=title,
                  bundle_files=bundle_files)


def write_sentinels(profile_path):
    credential = profile_path / 'creds'
    credential.mkdir(exist_ok=True)
    (credential / 'access.key').write_text('synthetic-private-key')
    settings = profile_path / 'configLibrary'
    settings.mkdir(exist_ok=True)
    (settings / 'CLAUDE.md').write_text('synthetic profile setting')
    (settings / 'configLibrary').write_text('synthetic nested setting')


sync = load_helper("claude_profile_sync")


class SyncFixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        policy = mock.patch.object(sync._records._identity._policy, 'managed_connection', return_value=False)
        policy.start()
        self.addCleanup(policy.stop)
        account = mock.patch.object(sync._records._identity, 'subscription', side_effect=subscription_identity)
        account.start()
        self.addCleanup(account.stop)
        self.first = profile(
            self.root, 'Claude', '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc')
        self.third = profile(
            self.root, 'Claude-3p', '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc')
        for profile_path in (self.first, self.third):
            for store in STORES:
                namespace(
                    profile_path, store,
                    json.loads((profile_path / 'config.json').read_text())[
                        'lastKnownAccountUuid'],
                    json.loads((profile_path / 'config.json').read_text())[
                        'lastKnownOrganizationUuid'])
        self.env = {
            'XDG_CONFIG_HOME': str(self.root),
            'CLAUDE_USER_DATA_DIR': str(self.third),
            'CLAUDE_CONFIG_DIR': str(self.root / 'claude-config'),
        }
        self.home = self.root / 'router'
        self.home.mkdir()

    def sync(self, winner='1p'):
        with mock.patch.object(sync, 'profile_roots', return_value=(self.first, self.third)):
            return sync.sync_profiles(self.home, winner, self.env)

    def paths(self, profile_path, store, session_id):
        groups = sync._records.group_records(profile_path / store)
        return groups.get(session_id, [])
