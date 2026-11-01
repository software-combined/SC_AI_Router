"""Read native desktop storage identity without changing sign-in or device state."""
import base64
import contextlib
import importlib.util
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
from pathlib import Path


_spec = importlib.util.spec_from_file_location(
    'router_identity_policy', Path(__file__).with_name('claude_desktop_policy.py'))
_policy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_policy)
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)
# Default organization observed in Claude 2.9939.2's static-gateway local stores.
STATIC_ORGANIZATION = '00000000-0000-4000-8000-000000000001'
BINDING = '.claude-profile-control-identity.json'


def _uuid(value):
    return value if isinstance(value, str) and UUID.fullmatch(value) else None


def subscription(profile):
    """Use a native session callback binding while its sign-in guard is current."""
    try:
        doc = _read_object(Path(profile) / BINDING)
        account, organization = _uuid(doc.get('account')), _uuid(doc.get('organization'))
        guard = _subscription_guard(profile)
        if (account and organization and same_guard(doc.get('guard'), guard)
                and account == guard['account']):
            return account, organization
    except (OSError, ValueError, TypeError, sqlite3.Error):
        pass
    return None


def same_guard(left, right):
    # Claude refreshes last_update_utc during ordinary navigation. Only the
    # cookie value and account invalidate an established native binding.
    return (isinstance(left, dict) and isinstance(right, dict)
            and all(left.get(key) == right.get(key) and right.get(key)
                    for key in ('account', 'organization_cookie')))


def bind_profile_accounts(home, first, third):
    """Do not expose an earlier account's gateway copies after a new sign-in.

    Returns the pair's digest when bound (it keys the shared-task ledger),
    False for a different pair and None while either account is unknown.
    """
    native, gateway = subscription(first), third_party(third)
    if not native or not gateway:
        return None
    identity = json.dumps([str(Path(first).resolve()), native[0],
                           str(Path(third).resolve()), gateway[0]])
    digest = hashlib.sha256(identity.encode()).hexdigest()
    path = Path(home) / '.claude-profile-control-accounts.json'
    try:
        saved = _read_object(path)
    except FileNotFoundError:
        # The caller holds both profile locks. Exclusive creation preserves a
        # concurrent or existing binding instead of reassigning its histories.
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump({'accounts': digest}, out)
            out.flush()
            os.fsync(out.fileno())
        return digest
    return digest if saved.get('accounts') == digest else False


def _read_object(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('unsafe identity metadata')
    if os.name != 'nt' and info.st_uid != os.getuid():
        raise ValueError('foreign identity metadata')
    doc = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(doc, dict):
        raise ValueError('invalid identity metadata')
    return doc


def _subscription_guard(profile):
    """Invalidate a captured binding on logout, account or organization change.

    These caches are change detectors only, never identity authority. Hash only
    the organization cookie ciphertext; no authentication cookie is read.
    """
    profile = Path(profile)
    config = _read_object(profile / 'config.json')
    account = _uuid(config.get('lastKnownAccountUuid'))
    if not account or config.get('windowSizeWasSignedIn') is not True:
        return None
    network = profile / 'Network'
    if network.is_symlink():
        return None
    cookies = network / 'Cookies'
    if not cookies.exists() and not cookies.is_symlink():
        cookies = profile / 'Cookies'
    for path in (profile, *profile.parents, cookies.parent, cookies,
                 cookies.with_name('Cookies-wal'), cookies.with_name('Cookies-shm')):
        if path.is_symlink():
            return None
    if not stat.S_ISREG(cookies.stat().st_mode) or cookies.stat().st_nlink != 1:
        return None
    with contextlib.closing(sqlite3.connect(
            cookies.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
        rows = db.execute("SELECT value, encrypted_value, last_update_utc FROM cookies WHERE "
                          "name='lastActiveOrg' AND host_key IN ('claude.ai','.claude.ai')").fetchall()
        signed_in = db.execute("SELECT count(*) FROM cookies WHERE name IN ('sessionKey','sessionKeyV2') "
                               "AND host_key IN ('claude.ai','.claude.ai') "
                               "AND length(value)+length(encrypted_value)>0").fetchone()[0]
    if len(rows) != 1 or not signed_in:
        return None
    plain, encrypted, updated = rows[0]
    if not plain and not encrypted:
        return None
    digest = hashlib.sha256(plain.encode() + b'\0' + encrypted).hexdigest()
    return {'account': account, 'organization_cookie': digest,
            'organization_updated_ms': (updated - 11644473600000000) // 1000}


def capture_subscription(profile, event, env):
    """Bind the exact task that Claude says it just started, without inference.

    Desktop sets HOST_SESSION_ID itself. The hook's CLI session ID must match
    that record in exactly one organization of the same signed-in account.
    An ambiguous or changed record never supplies an identity.
    """
    if (env.get('CLAUDE_CODE_ENTRYPOINT') != 'claude-desktop'
            or event.get('hook_event_name') != 'SessionStart'):
        return False
    host = env.get('CLAUDE_CODE_HOST_SESSION_ID', '')
    cli = _uuid(event.get('session_id'))
    if not isinstance(host, str) or not host.startswith('local_') or not _uuid(host[6:]) or not cli:
        return False
    try:
        profile = Path(profile)
        guard = _subscription_guard(profile)
        if not guard:
            return False
        root = profile / 'claude-code-sessions' / guard['account']
        if root.is_symlink() or root.parent.is_symlink():
            return False
        matches = []
        for org in root.iterdir():
            if not _uuid(org.name) or not org.is_dir() or org.is_symlink():
                continue
            path = org / (host + '.json')
            if not path.exists():
                continue
            record = _read_object(path)
            if (record.get('sessionId') == host and record.get('cliSessionId') == cli
                    and type(record.get('lastFocusedAt')) is int
                    and record['lastFocusedAt'] >= guard['organization_updated_ms']):
                matches.append(org.name)
        if len(matches) != 1 or not same_guard(_subscription_guard(profile), guard):
            return False
        spec = importlib.util.spec_from_file_location(
            'router_identity_atomic', Path(__file__).with_name('atomic_write.py'))
        atomic = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(atomic)
        atomic.replace_json(profile / BINDING, {
            'account': guard['account'], 'organization': matches[0], 'guard': guard})
        return True
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return False


def third_party(profile, platform_name=None):
    """Resolve the locally configured static gateway's native storage identity.

    Hosted, bootstrap and interactive deployments have different identity
    authorities and are outside the router's static gateway attachment.
    Never create or replace ant-did: only Claude owns device initialization.
    """
    try:
        if _policy.managed_connection(platform_name or sys.platform):
            return None
        entry = _policy.local_entry(profile)
        if (entry.get('inferenceProvider') != 'gateway'
                or entry.get('inferenceCredentialKind') != 'static'
                or not isinstance(entry.get('inferenceGatewayApiKey'), str)
                or not entry['inferenceGatewayApiKey'].strip()
                or any(key.startswith(('selfHosted', 'inferenceCredentialHelper'))
                       and value is not None for key, value in entry.items())):
            return None
        path = Path(profile) / 'ant-did'
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            return None
        raw = path.read_bytes()
        after = path.lstat()
        stamp = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if stamp(before) != stamp(after):
            return None
        account = _uuid(base64.b64decode(raw.strip(), validate=True).decode('utf-8').strip())
        organization = entry.get('deploymentOrganizationUuid')
        if organization is None or organization == '':
            organization = STATIC_ORGANIZATION
        elif isinstance(organization, str):
            organization = _uuid(organization.strip())
        else:
            organization = None
        return (account, organization) if account and organization else None
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        return None
