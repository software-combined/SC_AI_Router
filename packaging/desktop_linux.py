"""Read Linux desktop entries and Electron package identity without launching apps."""
import argparse
import configparser
import json
import os
import re
import shlex
import shutil
import stat
import struct
import sys
from pathlib import Path

APPS = {
    'codex': ('codex-desktop', 'ChatGPT', 'openai-codex-electron', 'Codex'),
    'claude': ('com.anthropic.Claude', 'claude-desktop', '@ant/desktop', 'Claude'),
}
MAX_DESKTOP_ENTRY = 64 * 1024
MAX_WRAPPER = 16 * 1024
MAX_ASAR_HEADER = 64 * 1024 * 1024
MAX_PACKAGE_JSON = 1024 * 1024
_ASSIGNMENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*=.*\Z')
_ENV_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')


def _refuse():
    raise OSError('Linux desktop identity could not be checked')

def _data_dirs():
    home = os.environ.get('XDG_DATA_HOME') or str(Path.home() / '.local/share')
    dirs = [home] + [d for d in (os.environ.get('XDG_DATA_DIRS') or
                                  '/usr/local/share:/usr/share').split(':') if d]
    paths = list(dict.fromkeys(Path(d) for d in dirs))
    if any(not path.is_absolute() for path in paths):
        _refuse()
    return paths

def _desktop_entry(desktop_id):
    for directory in _data_dirs():
        path = directory / 'applications' / (desktop_id + '.desktop')
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            _refuse()
        if not stat.S_ISREG(mode):
            _refuse()
        try:
            with path.open('rb') as source: raw = source.read(MAX_DESKTOP_ENTRY + 1)
            if len(raw) > MAX_DESKTOP_ENTRY:
                _refuse()
            parser = configparser.ConfigParser(interpolation=None, strict=True)
            parser.optionxform = str
            parser.read_string(raw.decode('utf-8-sig'))
            entry = parser['Desktop Entry']
            if (entry.get('Type') != 'Application' or any(
                    _boolean(entry, key) for key in ('Hidden', 'NoDisplay', 'Terminal',
                                                      'DBusActivatable'))):
                _refuse()
            return _exec_argv(entry['Exec'])
        except (OSError, UnicodeError, configparser.Error, KeyError, ValueError) as exc:
            _refuse()
    _refuse()

def _boolean(entry, key):
    value = entry.get(key, 'false').lower()
    if value not in ('true', 'false'): _refuse()
    return value == 'true'

def _exec_argv(command):
    fields, quoted, index = [], False, 0
    while index < len(command):
        char = command[index]
        if char == '\\':
            if not quoted or index + 1 == len(command) or command[index + 1] not in '"\\$`': _refuse()
            index += 2
            continue
        if char == '"':
            quoted = not quoted
        elif char == '%':
            if index + 1 < len(command) and command[index + 1] == '%':
                index += 2
                continue
            if (index == 0 or index + 1 == len(command) or command[index + 1] not in 'fFuU'
                    or quoted or not command[:index].strip()
                    or (index and not command[index - 1].isspace())
                    or (index + 2 < len(command) and not command[index + 2].isspace())):
                _refuse()
            fields.append(index)
            index += 2
            continue
        elif not quoted and char in "'<>~|&;$*?#()`": _refuse()
        index += 1
    if quoted or len(fields) > 1:
        _refuse()
    for offset in reversed(fields):
        command = command[:offset] + command[offset + 2:]
    try:
        result = shlex.split(command.replace('%%', '%'))
    except ValueError as exc:
        _refuse()
    if not result or not result[0] or '=' in result[0]: _refuse()
    return result

def _command_path(argv):
    command, args = argv[0], argv[1:]
    search_path = os.environ.get('PATH', os.defpath)
    if Path(command).name == 'env':
        if not Path(command).is_absolute() and '/' in command: _refuse()
        while args and _ASSIGNMENT.fullmatch(args[0]):
            name, value = args.pop(0).split('=', 1)
            if not _ENV_NAME.fullmatch(name): _refuse()
            if name == 'PATH':
                paths = value.split(os.pathsep)
                if any(not part or not Path(part).is_absolute() for part in paths): _refuse()
                search_path = os.pathsep.join(paths)
        if not args or args[0].startswith('-'): _refuse()
        command, args = args[0], args[1:]
    if Path(command).is_absolute():
        candidate = Path(command)
    else:
        if '/' in command or command in ('.', '..') or '=' in command: _refuse()
        found = shutil.which(command, path=search_path)
        if not found: _refuse()
        candidate = Path(found)
    try:
        candidate = candidate.resolve(strict=True)
        mode = candidate.stat().st_mode
    except OSError as exc:
        _refuse()
    if not stat.S_ISREG(mode) or not os.access(candidate, os.X_OK): _refuse()
    return candidate

def _wrapper_target(wrapper, expected_executable):
    try:
        with wrapper.open('rb') as source:
            raw = source.read(MAX_WRAPPER + 1)
        if len(raw) > MAX_WRAPPER:
            _refuse()
        lines = raw.decode('utf-8').splitlines()
    except (OSError, UnicodeError) as exc:
        _refuse()
    if not lines or lines[0] not in ('#!/bin/sh', '#!/usr/bin/env sh'):
        _refuse()
    body = [line.strip() for line in lines[1:] if line.strip() and not line.lstrip().startswith('#')]
    if len(body) != 1 or not body[0].endswith(' "$@"'): _refuse()
    try:
        words = shlex.split(body[0])
    except ValueError as exc:
        _refuse()
    if len(words) != 3 or words[0] != 'exec' or words[2] != '$@': _refuse()
    target = Path(words[1])
    if not target.is_absolute(): _refuse()
    try:
        target = target.resolve(strict=True)
        mode = target.stat().st_mode
    except OSError as exc:
        _refuse()
    if not stat.S_ISREG(mode) or not os.access(target, os.X_OK) or target.name != expected_executable: _refuse()
    return target

def _is_script(path):
    try:
        with path.open('rb') as source:
            return source.read(2) == b'#!'
    except OSError as exc:
        _refuse()

def _package_version(archive, expected_name, expected_product):
    try:
        if not stat.S_ISREG(archive.lstat().st_mode): _refuse()
        with archive.open('rb') as source:
            size = archive.stat().st_size
            prefix = source.read(8)
            if len(prefix) != 8: _refuse()
            pickle_size, header_size = struct.unpack('<II', prefix)
            if pickle_size != 4 or not 8 <= header_size <= min(MAX_ASAR_HEADER, size - 8):
                _refuse()
            header_pickle = source.read(header_size)
            if len(header_pickle) != header_size: _refuse()
            index_text = _read_pickle_string(header_pickle)
            entry = json.loads(index_text)['files']['package.json']
            offset, package_size = entry['offset'], entry['size']
            if (not isinstance(offset, str) or not re.fullmatch(r'[0-9]+', offset)
                    or isinstance(package_size, bool) or not isinstance(package_size, int)
                    or not 2 <= package_size <= MAX_PACKAGE_JSON):
                _refuse()
            data_offset = 8 + header_size + int(offset)
            if data_offset < 0 or data_offset + package_size > size: _refuse()
            source.seek(data_offset)
            raw = source.read(package_size)
            if len(raw) != package_size: _refuse()
        package = json.loads(raw.decode('utf-8'))
        if not isinstance(package, dict) or package.get('name') != expected_name or package.get('productName') != expected_product: _refuse()
        version = package.get('version')
        if not isinstance(version, str) or not version or len(version) > 128 or any(ord(c) < 32 for c in version): _refuse()
        return version
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, struct.error) as exc:
        _refuse()

def _read_pickle_string(value):
    if len(value) < 8: _refuse()
    payload_size, string_size = struct.unpack_from('<II', value)
    padded = (string_size + 3) & ~3
    if payload_size != len(value) - 4 or 8 + padded != len(value): _refuse()
    return value[8:8 + string_size].decode('utf-8')

def app_identity(app):
    try:
        desktop_id, executable_name, package_name, product_name = APPS[app]
    except (KeyError, TypeError):
        _refuse()
    argv = _desktop_entry(desktop_id)
    executable = _command_path(argv)
    if executable.name != executable_name or _is_script(executable):
        executable = _wrapper_target(executable, executable_name)
    root = executable.parent.resolve()
    version = _package_version(root / 'resources' / 'app.asar', package_name, product_name)
    return {
        'root': str(root), 'exe': str(executable), 'user': str(os.getuid()),
        'desktop_id': desktop_id, 'package_version': version,
    }

def main(argv=None):
    parser = argparse.ArgumentParser(description='Read a Linux desktop app identity.')
    parser.add_argument('--app', choices=tuple(APPS), required=True)
    args = parser.parse_args(argv)
    if sys.platform != 'linux':
        print('Linux desktop identity checks are available on Linux only.', file=sys.stderr)
        return 1
    try:
        identity = app_identity(args.app)
    except Exception:
        print('Could not verify the selected Linux desktop package.', file=sys.stderr)
        return 1
    print(json.dumps(dict(app=args.app, **identity), sort_keys=True))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
