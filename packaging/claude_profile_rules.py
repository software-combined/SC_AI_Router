"""Screening and path rules for Claude profile session transfers."""
import json
import io
import ntpath
import os
import re
import shutil
import stat
from pathlib import Path


DROP_KEYS = frozenset({
    'accountName', 'emailAddress', 'oauthAccount', 'userID',
    'org', 'orgId', 'orgUuid', 'organization', 'organizationId',
    'organizationUuid', 'lastKnownOrg', 'lastKnownOrgId', 'lastKnownOrgUuid',
    'lastKnownOrganization', 'lastKnownOrganizationId',
    'lastKnownOrganizationUuid',
    'remoteMcpServersConfig', 'enabledMcpTools', 'pluginInstallPaths',
    'orgCliExecPolicies', 'egressAllowedDomains', 'webFetchAllowedUrls',
    'chromePermsBeforeUnsupervised', 'sessionPermissionUpdates',
    'promptAppendSnapshot', 'toolSurfaceSnapshot', 'cliBinaryPin',
})
DROP_KEY_TOKENS = (
    'token', 'secret', 'password', 'credential', 'oauth', 'apikey',
    'authorization', 'privatekey', 'email', 'account', 'userid', 'useruuid',
    'orgid', 'orguuid', 'organizationid', 'organizationuuid',
)
DROP_NAME_PARTS = frozenset(part.lower() for part in {
    'creds', 'backup', 'backups', 'receipts', 'journal', 'journals',
    'manifest', 'manifests', 'journal.json', 'manifest.json',
    'pending', 'recovery', 'usage-ledger', 'rpm', 'skills-plugin', 'uploads-tmp',
    'plugin-cache', 'plugin_cache', 'plugins-cache', '.claude-plugin',
    'configLibrary', 'activation' + '.json', 'claude_desktop_config.json',
    'config.json', 'state.json', 'policy-limits.json', '.last-cleanup',
    '.audit-key', '.claude.json', 'CLAUDE.md',
})
DROP_NAME_TOKENS = (
    'token', 'secret', 'password', 'credential', 'oauth', 'apikey',
    'authorization', 'privatekey', 'accountid', 'accountname', 'accountuuid',
    'emailaddress', 'userid', 'useruuid', 'orgid', 'orguuid',
    'organizationid', 'organizationuuid',
    'mcpauth', 'netrc', 'idrsa', 'ided25519',
)
DROP_FILE_NAMES = frozenset(name.lower() for name in {
    '.env', '.netrc', 'auth.json', 'credentials.json', 'credentials.txt',
    'mcp-auth.json', 'secrets.json', 'secret.json', 'settings.local.json',
    'settings.json', 'managed-settings.json', 'permissions.json', 'trust.json',
})
DROP_FILE_SUFFIXES = ('.key', '.pem', '.p12', '.pfx')
WORKSPACE_FOLDER = re.compile(r'[A-Za-z0-9-]+')
CREDENTIAL_CONTENT_PATTERNS = tuple(re.compile(pattern.encode(), re.I) for pattern in (
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----',
    r'\b(?:authorization|proxy-authorization)\s*:',
    r'\bbearer\s+[A-Za-z0-9._~+/\-=]{8,}',
    r'\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|token|secret)\s*["\']?\s*[:=]\s*["\']?[^\s,;]{4,}',
    r'\b(?:secret[_-]?access[_-]?key|aws[_-]?secret[_-]?access[_-]?key)\s*[:=]\s*[^\s,;]{4,}',
    r'\b(?:set-cookie|cookie)\s*:',
    r'\b(?:sessionid|jsessionid|phpsessid|sid)\s*[:=]\s*[^\s;,]{4,}',
    r'\bAKIA[0-9A-Z]{16}\b',
    r'\bASIA[0-9A-Z]{16}\b',
    r'\bgh[pousr]_[A-Za-z0-9]{20,}\b',
    r'\bgithub_pat_[A-Za-z0-9_]{20,}\b',
    r'\bsk-[A-Za-z0-9_-]{16,}\b',
    r'\bsk_(?:live|test)_[A-Za-z0-9]{10,}\b',
    r'\bxox[aboprs]-[A-Za-z0-9-]{10,}\b',
    r'\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b',
    r'\bya29\.[A-Za-z0-9._~+/-]{10,}\b',
    r'\b(?:1//|glsa_)[A-Za-z0-9._~+/-]{16,}\b',
))
PATH_KEYS = frozenset({
    'cwd', 'originCwd', 'path', 'workspace', 'projectDir', 'file',
    'absolutePath', 'outputPath', 'uploadPath',
})
CONVERSATION_KEYS = frozenset({
    'message', 'messages', 'toolUseResult', 'text', 'title', 'initialMessage',
    'previousTitles', 'postTurnSummary', 'promptSuggestion', 'scratchPromptRecents',
    'wireToolInputs', 'attachment', 'rendered',
})


def normalized_key(name):
    return ''.join(char for char in str(name).lower() if char.isalnum())


DROP_KEYS_NORMALIZED = frozenset(normalized_key(key) for key in DROP_KEYS)


def local_key(name):
    normalized = normalized_key(name)
    return (name in DROP_KEYS or normalized in DROP_KEYS_NORMALIZED
            or any(token in normalized for token in DROP_KEY_TOKENS))


def safe_component(value):
    return (isinstance(value, str) and value not in ('', '.', '..')
            and '/' not in value and '\\' not in value and '\x00' not in value)


def safe_filename(value):
    return (safe_component(value)
            and not any(char in value for char in '*?[]'))


def skip(path, history=False):
    """True for a name that never transfers; `history` means relative to `projects`.

    Claude Code names each folder in `.claude/projects` after the task's
    workspace, using letters, digits and dashes, so its words are the user's
    own (oauth-demo, migration-before). That folder skips only the word screen
    and the dashed -before/-after suffixes; the router's markers use dots.
    """
    parts = Path(path).parts
    if history:
        workspace_index = 0
    elif [part.lower() for part in parts[:2]] == ['.claude', 'projects']:
        workspace_index = 2
    else:
        workspace_index = None
    for index, part in enumerate(parts):
        lower = part.lower()
        normalized = normalized_key(part)
        screened = not (index == workspace_index and WORKSPACE_FOLDER.fullmatch(part))
        if (lower in DROP_NAME_PARTS or lower in DROP_FILE_NAMES
                or lower.endswith(DROP_FILE_SUFFIXES)
                or lower.endswith(('.backup', '.pending', '.tmp', '.journal',
                                   '.manifest', '.recovery'))
                or (screened and lower.endswith(('-before', '-after')))
                or (lower.startswith('receipt') and lower.endswith('.json'))
                or any(token in lower for token in (
                    '.tmp-', '.before-', '.after-', '.duplicate-backup-',
                    '.recovery-', 'transaction-manifest',
                    'claude-profile-transaction', 'claude-profile-control'))
                or lower.startswith(('plugin_', 'host-creds-'))
                or (screened and any(token in normalized for token in DROP_NAME_TOKENS))):
            return True
    return False


def regular(path):
    try:
        return stat.S_ISREG(Path(path).lstat().st_mode)
    except OSError:
        return False


def clean(value):
    if isinstance(value, dict):
        out = {}
        for name, item in value.items():
            if local_key(name):
                continue
            cleaned = clean(item)
            out[name] = cleaned
        return out
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


def _replace_prefix(value, old, new):
    windows = os.name == 'nt' or bool(ntpath.splitdrive(str(old))[0])
    old_text, candidate = str(old).rstrip('/\\'), value
    new_text = str(new).rstrip('/\\')
    if windows:
        prefix = old_text.replace('\\', '/').split('/')
        parts = value.replace('\\', '/').split('/')
        if [part.casefold() for part in parts[:len(prefix)]] != [part.casefold() for part in prefix]:
            return value
        separator = '\\' if '\\' in new_text else '/'
        return separator.join([new_text] + parts[len(prefix):])
    if candidate == old_text or candidate.startswith(old_text + '/'):
        suffix = value[len(old_text):]
        return new_text + suffix
    return value


def rewrite_path(value, source_bundle, target_bundle, source_profile,
                 target_profile):
    if not isinstance(value, str):
        return value
    for old, new in ((source_bundle, target_bundle),
                     (source_profile, target_profile)):
        if old is None or new is None:
            continue
        value = _replace_prefix(value, old, new)
    return value


def rewrite(value, paths):
    if isinstance(value, dict):
        out = {}
        for name, item in value.items():
            if (name in PATH_KEYS and isinstance(item, str)
                    and len(paths or ()) == 4):
                out[name] = rewrite_path(item, *paths)
            else:
                out[name] = rewrite(item, paths)
        return out
    if isinstance(value, list):
        return [rewrite(item, paths) for item in value]
    return value


def contains_credential(data):
    return any(pattern.search(data) for pattern in CREDENTIAL_CONTENT_PATTERNS)


def assert_clean_bytes(data, source):
    if contains_credential(data):
        raise ValueError('credential-like content: %s' % source)


def assert_clean_file(source):
    path = Path(source)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('artifact is too large to screen: %s' % source)
    assert_clean_bytes(path.read_bytes(), source)


def _write_text(target, output, mode=None):
    target = Path(target)
    if target.exists():
        existing = target.stat().st_mode & 0o777
        mode = existing if mode is None else mode & existing
    elif mode is None:
        mode = 0o600
    target.write_text(output, encoding='utf-8')
    target.chmod(mode)


def _merge_local(existing, incoming):
    if isinstance(existing, dict) and isinstance(incoming, dict):
        out = dict(incoming)
        for name, item in existing.items():
            if local_key(name):
                out[name] = item
            elif name in out and name not in CONVERSATION_KEYS:
                out[name] = _merge_local(item, out[name])
        return out
    return incoming


def _merge_winner(base, winner, local_source):
    if not isinstance(base, dict) or not isinstance(winner, dict):
        return winner
    out = {}
    for name in set(base) | set(winner):
        if local_key(name):
            if name in local_source:
                out[name] = local_source[name]
            elif name in winner:
                out[name] = winner[name]
            elif name in base:
                out[name] = base[name]
        elif name in CONVERSATION_KEYS:
            out[name] = winner[name] if name in winner else base[name]
        elif name in winner:
            out[name] = _merge_winner(
                base.get(name, {}), winner[name], local_source.get(name, {}))
        else:
            out[name] = base[name]
    return out


def project_record(raw, paths, existing=None, target_wins=False,
                   existing_paths=None):
    """Return safe transfer JSON text while retaining target-local fields."""
    incoming = transcript_row(raw, paths)
    assert_clean_record(incoming)
    if existing is None:
        return json.dumps(incoming)
    existing_paths = existing_paths or (paths[1], paths[1], paths[3], paths[3])
    existing_transfer = transcript_row(existing, existing_paths)
    if target_wins:
        merged = _merge_winner(incoming, existing_transfer, existing)
    else:
        merged = _merge_winner(existing_transfer, incoming, existing)
    return json.dumps(_merge_local(existing, merged), sort_keys=True)


def transcript_row(doc, paths=(), keep=False):
    # Message and tool payloads are conversation data, not profile settings.
    # Keep pasted keys too; only separate application credentials are excluded.
    # A transcript row (keep=True) loses no key; only relocated paths change.
    payloads = CONVERSATION_KEYS
    body = {key: value for key, value in doc.items() if key not in payloads}
    result = rewrite(body if keep else clean(body), paths)
    result.update({key: doc[key] for key in payloads if key in doc})
    return result


def assert_clean_record(doc):
    metadata = {key: value for key, value in doc.items() if key not in CONVERSATION_KEYS}
    assert_clean_bytes(json.dumps(metadata, sort_keys=True).encode(), 'record')


def copy_transcript(source, target, paths, mode=None):
    """Copy every row; rows without a relocated path keep their exact text."""
    lines = []
    for line in io.StringIO(Path(source).read_text(encoding='utf-8')):
        if not line.strip():
            lines.append(line)
            continue
        try:
            doc = json.loads(line)
        except ValueError as exc:
            raise ValueError('invalid JSONL: %s' % source) from exc
        if not isinstance(doc, dict):
            raise ValueError('JSONL row is not an object: %s' % source)
        projected = transcript_row(doc, paths, keep=True)
        # Checkpoint entries are keyed by the user's file names, such as
        # config/secret, and are conversation data rather than credentials.
        assert_clean_record({key: value for key, value in projected.items()
                             if key != 'snapshot'})
        lines.append(line if projected == doc
                     else json.dumps(projected, ensure_ascii=False) + '\n')
    _write_text(target, ''.join(lines), mode)


def copy_file(source, target, paths, mode=None, *, conversation=False):
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if conversation:
        copy_transcript(source, target, paths, mode)
        return
    existing_mode = (target.stat().st_mode & 0o777
                     if target.exists() else None)
    # Task files, including integrity-chained audit logs, keep their exact bytes.
    assert_clean_file(source)
    shutil.copy2(source, target)
    if mode is not None:
        target.chmod(mode if existing_mode is None else mode & existing_mode)
