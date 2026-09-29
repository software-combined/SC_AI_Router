"""Read Claude's local switch restriction and native managed sources.

Only a locally controlled connection is accepted. Managed connection settings
can supersede the router attachment, so they refuse switching; update, lifecycle
and proxy policies alone leave the selected local configuration in control.
The switch check returns only a decision. Policy values are never written or logged.
"""
import json
import os
import plistlib
import re
import stat
from pathlib import Path


DISABLE = 'disableDeploymentModeChooser'
APP_BEHAVIOR = frozenset(key.casefold() for key in (
    'disableAutoUpdates', 'autoUpdaterEnforcementHours', 'updateViaUpdatesHost',
    'relaunchEnforcementHours', 'configRecheckIntervalMinutes',
    'egressProxyUrl', 'egressProxyPacUrl'))
UNKNOWN = 'effective Claude policy is unknown'


def _document(path, *, plist=False):
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise OSError(UNKNOWN)
    with path.open('rb') as stream:
        doc = plistlib.load(stream) if plist else json.loads(stream.read().decode('utf-8'))
        after = os.fstat(stream.fileno())
    stamp = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    if stamp(before) != stamp(after) or stamp(after) != stamp(path.lstat()):
        raise OSError(UNKNOWN)
    if not isinstance(doc, dict):
        raise OSError(UNKNOWN)
    return doc


def _disabled(value):
    if isinstance(value, bool):
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        value = value.strip().replace('\r', '').lower()
        if value in ('true', '1', 'false', '0'):
            return value in ('true', '1')
    raise OSError(UNKNOWN)


def local_entry(profile):
    library = Path(profile) / 'configLibrary'
    if not stat.S_ISDIR(library.lstat().st_mode):
        raise OSError(UNKNOWN)
    meta = _document(library / '_meta.json')
    identifier = meta.get('appliedId')
    if (meta.get('hybridPointer') or not isinstance(identifier, str)
            or not re.fullmatch(r'[a-f0-9-]{36}', identifier)):
        raise OSError(UNKNOWN)
    doc = _document(library / (identifier + '.json'))
    if doc.get('bootstrapUrl'):
        raise OSError(UNKNOWN)
    return doc


def local_disabled(profile):
    doc = local_entry(profile)
    return _disabled(doc[DISABLE]) if DISABLE in doc else False


def managed_macos(paths=None):
    if paths is None:
        import pwd
        username = pwd.getpwuid(os.getuid()).pw_name
        if not username or '/' in username:
            raise OSError(UNKNOWN)
        base = Path('/Library/Managed Preferences')
        filename = 'com.anthropic.claudefordesktop.plist'
        paths = (base / filename, base / username / filename)
    result = {}
    # The installed desktop reads machine preferences, then user preferences.
    for path in paths:
        try:
            result.update(_document(path, plist=True))
        except FileNotFoundError:
            continue
    return result


def managed_windows(registry=None):
    if registry is None:
        import winreg as registry
    for hive in (registry.HKEY_LOCAL_MACHINE, registry.HKEY_CURRENT_USER):
        try:
            key = registry.OpenKey(hive, r'SOFTWARE\Policies\Claude',
                                   0, registry.KEY_READ | registry.KEY_WOW64_64KEY)
        except FileNotFoundError:
            continue
        values = {}
        with key:
            index = 0
            while True:
                try:
                    name, value, kind = registry.EnumValue(key, index)
                except OSError as exc:
                    if getattr(exc, 'winerror', None) != 259:
                        raise
                    break
                index += 1
                if kind in (registry.REG_SZ, registry.REG_DWORD, registry.REG_EXPAND_SZ):
                    # Expandable strings establish policy presence but Claude
                    # cannot read them. Preserve that uncertainty, not their data.
                    values[name] = None if kind == registry.REG_EXPAND_SZ else value
        if values:
            return values
    return {}


def managed_linux(path=Path('/etc/claude-desktop/managed-settings.json')):
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {}
    parent = path.parent.lstat()
    if (not stat.S_ISREG(info.st_mode) or not stat.S_ISDIR(parent.st_mode)
            or any(item.st_uid != 0 or item.st_mode & 0o022 for item in (info, parent))):
        raise OSError(UNKNOWN)
    return _document(path)


def managed_connection(platform_name):
    readers = {'darwin': managed_macos, 'win32': managed_windows, 'linux': managed_linux}
    managed = readers[platform_name]()
    if any(value is None for value in managed.values()):
        raise OSError(UNKNOWN)
    return any(key.casefold() not in APP_BEHAVIOR for key in managed)


def policy_disabled(platform_name, profile):
    try:
        if profile is None:
            raise OSError(UNKNOWN)
        if local_disabled(profile):
            return True
        # Any connection-level policy could replace the locally verified
        # gateway. Do not assume its absence of a sign-in flag grants authority.
        return managed_connection(platform_name)
    except (OSError, ValueError, TypeError, KeyError, ImportError) as exc:
        raise OSError(UNKNOWN) from exc
