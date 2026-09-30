"""Profile, namespace and record discovery for Claude session sync."""
import importlib.util
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_desktop = _load('router_claude_records_desktop', 'claude_desktop_config.py')
_rules = _load('router_claude_records_rules', 'claude_profile_rules.py')
_identity = _load('router_claude_profile_identity', 'claude_profile_identity.py')

# Only Code tasks are shared in the 1.0.0 beta. Cowork layout support below stays
# tested; add 'local-agent-mode-sessions' back here to share Cowork tasks again.
STORES = ('claude-code-sessions',)
PROFILE_NAMES = {'1p': 'Claude', '3p': 'Claude-3p'}
RECORD_GLOB = 'local_*.json'
NATIVE_SESSION = re.compile(r'local_([0-9a-f]{8})-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
RECEIPT_NAME = 'activation' + '.json'


def assert_ancestors(path):
    path = Path(path).absolute()
    for current in reversed((path,) + tuple(path.parents)):
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('unsafe session path')


def assert_target(path, root):
    path, root = Path(path), Path(root)
    assert_ancestors(path)
    assert_ancestors(root)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError('unsafe session path') from exc
    current = root
    for part in relative.parts:
        if not _rules.safe_component(part):
            raise ValueError('unsafe session path')
        current /= part
        if current.is_symlink():
            raise ValueError('unsafe session path')
    resolved_root, resolved = root.resolve(), path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError('unsafe session path')


def safe_target(path, root):
    try:
        assert_target(path, root)
    except ValueError:
        return False
    return True


def read_json(path):
    assert_ancestors(path)
    if not _rules.regular(path):
        raise ValueError('invalid-record')
    try:
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('invalid JSON: %s' % path) from exc
    if not isinstance(doc, dict):
        raise ValueError('JSON is not an object: %s' % path)
    return doc


def _receipt_third_party(home):
    if home is None:
        return None
    path = Path(home) / RECEIPT_NAME
    assert_ancestors(path)
    if not path.exists():
        return None
    clients = read_json(path).get('clients', {})
    if not isinstance(clients, dict):
        raise ValueError('invalid desktop attachment')
    if 'claude-desktop' not in clients:
        return None
    try:
        entry = clients['claude-desktop']
        config_path = Path(entry['config_path'])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError('invalid desktop attachment') from exc
    if (not config_path.is_absolute()
            or config_path.parent.name != 'configLibrary'):
        raise ValueError('invalid desktop attachment')
    return config_path.parents[1]


def profile_roots(env=None, platform_name=None, home=None):
    """Return the native first-party root and receipt-aware third-party root."""
    env = os.environ if env is None else env
    platform_name = sys.platform if platform_name is None else platform_name
    first = _desktop.profile_root(env, platform_name) / PROFILE_NAMES['1p']
    third = _desktop.user_data_dir(env, platform_name)
    receipt_third = _receipt_third_party(home)
    if receipt_third is not None:
        if (env.get('CLAUDE_USER_DATA_DIR')
                and Path(env['CLAUDE_USER_DATA_DIR']).expanduser() != receipt_third):
            raise ValueError('third-party profile override disagrees with attachment')
        third = receipt_third
    return first, third


def _identity_variants(value, store_name):
    if store_name == 'local-agent-mode-sessions':
        return {value, value[:8]}
    return {value}


def namespace_paths(store_root):
    store_root = Path(store_root)
    assert_ancestors(store_root)
    if not store_root.is_dir():
        return []
    paths = []
    for account in store_root.iterdir():
        if (not account.is_dir() or account.is_symlink()
                or _rules.skip(Path(account.name))
                or not safe_target(account, store_root)):
            continue
        for org in account.iterdir():
            if (not org.is_dir() or org.is_symlink()
                    or _rules.skip(Path(org.name))
                    or not safe_target(org, store_root)):
                continue
            paths.append((account, org))
    return sorted(paths, key=lambda item: (item[0].name, item[1].name))


def resolve_namespace(store_root, profile_root, *, third_party=False):
    """Resolve one positively identified target namespace or return None."""
    store_root = Path(store_root)
    assert_target(store_root, profile_root)
    assert_target(Path(profile_root) / 'config.json', profile_root)
    if third_party:
        assert_target(Path(profile_root) / 'ant-did', profile_root)
        assert_target(Path(profile_root) / 'configLibrary', profile_root)
        account, organization = _identity.third_party(profile_root) or (None, None)
    else:
        account, organization = _identity.subscription(profile_root) or (None, None)
    candidates = namespace_paths(store_root)
    if account and organization:
        matches = [item for item in candidates
                   if item[0].name in _identity_variants(account, store_root.name)]
        compatible = [
            item for item in matches
            if item[1].name in _identity_variants(organization, store_root.name)
        ]
        if len(compatible) == 1:
            return compatible[0]
        if compatible or matches:
            return None
    else:
        return None
    namespace = store_root / account / organization
    assert_target(namespace, store_root)
    return namespace.parent, namespace


def record_paths(store_root, include_irregular=False, *, account=None, org=None):
    store_root = Path(store_root)
    assert_ancestors(store_root)
    if not store_root.is_dir():
        return []
    records = []
    for account_dir, org_dir in namespace_paths(store_root):
        if ((account is not None and account_dir != account)
                or (org is not None and org_dir != org)):
            continue
        containers = [org_dir]
        if store_root.name == 'local-agent-mode-sessions' and safe_target(org_dir / 'agent', store_root):
            containers.append(org_dir / 'agent')
        records.extend(path for container in containers for path in container.glob(RECORD_GLOB)
                       if include_irregular or (_rules.regular(path) and not path.is_symlink()))
    return sorted(records)


def valid_pair_paths(store_root, record, bundle, identifier):
    """Bind recovery authority to a full bundle or its native UUID abbreviation."""
    if not record.name.startswith('local_') or record.suffix != '.json':
        return False
    if bundle == record.with_suffix(''):
        return True
    match = NATIVE_SESSION.fullmatch(record.stem)
    if (store_root.name != 'local-agent-mode-sessions' or not match
            or identifier != record.stem or bundle != record.parent / match[1]
            or record.with_suffix('').exists() or record.with_suffix('').is_symlink()):
        return False
    # Native full directories win; only unresolved abbreviations can collide.
    for other in record.parent.glob('local_' + match[1] + '-*.json'):
        if other != record and NATIVE_SESSION.fullmatch(other.stem):
            assert_ancestors(other.with_suffix(''))
            if not other.with_suffix('').is_dir():
                return False
    return True


def bundle_path(record, store_root):
    full = record.with_suffix('')
    assert_target(full, store_root)
    match = NATIVE_SESSION.fullmatch(record.stem)
    if full.exists() or store_root.name != 'local-agent-mode-sessions' or not match:
        return full
    short = record.parent / match[1]
    assert_target(short, store_root)
    if not short.exists():
        return full
    if not short.is_dir() or not valid_pair_paths(store_root, record, short, session_id(read_json(record))):
        raise ValueError('ambiguous session bundle')
    return short


def session_id(record):
    value = record.get('sessionId')
    if not isinstance(value, str) or not value or '\x00' in value:
        raise ValueError('invalid session id')
    return value


def group_records(store_root, include_irregular=False, *, account=None, org=None):
    groups = {}
    for path in record_paths(store_root, include_irregular, account=account, org=org):
        if path.is_symlink() or not _rules.regular(path):
            continue
        try:
            identifier = session_id(read_json(path))
        except ValueError:
            continue
        groups.setdefault(identifier, []).append(path)
    return groups


def record_state(path):
    path = Path(path)
    stat_result = path.lstat()
    return ((stat_result.st_mode, stat_result.st_size,
             stat_result.st_mtime_ns, stat_result.st_ino),
            hashlib.sha256(path.read_bytes()).hexdigest())


def record_snapshot(paths):
    return {Path(path): record_state(path) for path in paths}


def assert_record_snapshot(snapshot):
    for path, state in snapshot.items():
        try:
            current = record_state(path)
        except OSError:
            current = None
        if current != state:
            raise ValueError('source record changed during sync')
