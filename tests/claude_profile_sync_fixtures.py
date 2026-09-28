"""Shared synthetic fixtures for Claude profile session sync tests."""
import base64
import hashlib
import importlib.util
import json
import stat
from pathlib import Path


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
