"""Lossless receipt comparison; parsed values never leave the verifier process.

Only the single-line root assignments the installer writes are editable.
Other root assignments and comments survive outside the managed region.
Python 3.9 entrypoints use the managed interpreter for standard-library TOML.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

BEGIN = '# BEGIN local mixed model picker'
END = '# END local mixed model picker'
PICKS = ('model', 'model_reasoning_effort')
CONNECTION_KEYS = {'openai_base_url', 'model_provider', 'model_providers', 'model_catalog_json'}
HAS_TOML = sys.version_info >= (3, 11)
PYTHON = None  # The installer's resolved runtime, including an explicit --python.
run = subprocess.run
CONFLICT = 'Router settings changed; leaving configuration untouched for manual review.'


def read(path):
    with Path(path).open(newline='') as stream:
        return stream.read()


def parser_python():
    if PYTHON:
        return PYTHON
    home = Path(__file__).resolve().parents[3]
    candidates = (home / 'runtime/python/bin/python3.14',
                  home / 'runtime/python/python.exe')
    return next((str(path) for path in candidates if path.is_file()),
                shutil.which('python3.14'))


def _verified(text, recorded=None):
    import tomllib
    if recorded is None:
        tomllib.loads(text)
        return {}
    if not isinstance(recorded, str) or not recorded:
        raise ValueError('receipt')
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError('markers')
    lines = text.splitlines(keepends=True)
    first = next(i for i, line in enumerate(lines) if line.strip() == BEGIN)
    last = next(i for i, line in enumerate(lines) if line.strip() == END)
    if last <= first or any(line.lstrip().startswith('[') for line in lines[:first]):
        raise ValueError('scope')
    # An unfinished literal before the marker would make this region data.
    tomllib.loads(''.join(lines[:first]))
    region = ''.join(lines[first:last + 1])
    # Retain the existing repair of duplicate owner picks: the last wins.
    # Routing keys never receive this normalization.
    def unique_picks(value):
        rows = value.splitlines(keepends=True)
        selected = {line.split('=', 1)[0].strip(): index for index, line in enumerate(rows)
                    if '=' in line and line.split('=', 1)[0].strip() in PICKS}
        return ''.join(line for index, line in enumerate(rows)
                       if line.split('=', 1)[0].strip() not in selected
                       or selected[line.split('=', 1)[0].strip()] == index)
    expected = tomllib.loads(unique_picks(recorded))
    actual = tomllib.loads(unique_picks(region))
    if (recorded.count(BEGIN) != 1 or recorded.count(END) != 1
            or not CONNECTION_KEYS.intersection(expected)):
        raise ValueError('receipt')
    if CONNECTION_KEYS.intersection(actual) - expected.keys():
        raise ValueError('connection')
    for key, value in expected.items():
        if key not in PICKS and actual.get(key) != value:
            raise ValueError('connection')
    keep = []
    if region == recorded:  # legacy receipt blocks may contain owned tables
        return {'start': sum(map(len, lines[:first])),
                'end': sum(map(len, lines[:last + 1])), 'keep': keep}
    for index in range(first + 1, last):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith('#'):
            if line.strip() and line.strip() not in recorded.splitlines():
                keep.append(index)
            continue
        # A multiline literal or table needs a different lossless edit. Refuse
        # rather than interpreting a continuation as a root assignment.
        row = tomllib.loads(line)
        if len(row) != 1 or line.lstrip().startswith('['):
            raise ValueError('shape')
        key = next(iter(row))
        if key not in expected and key not in PICKS:
            keep.append(index)
    return {'start': sum(map(len, lines[:first])),
            'end': sum(map(len, lines[:last + 1])), 'keep': keep}


def inspect(text, recorded=None):
    try:
        if HAS_TOML:
            return _verified(text, recorded)
        python = parser_python()
        if not python:
            raise ValueError('interpreter')
        result = run([python, str(Path(__file__).resolve()), '--verify'],
                     input=json.dumps({'text': text, 'recorded': recorded}),
                     capture_output=True, text=True, timeout=15)
        if result.returncode or len(result.stdout) > 65536:
            raise ValueError('verifier')
        return json.loads(result.stdout)
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
        raise SystemExit(CONFLICT) from None


def region(text, recorded):
    proof = inspect(text, recorded)
    return text[proof['start']:proof['end']]


def replace(text, recorded, block):
    proof = inspect(text, recorded)
    lines = text.splitlines(keepends=True)
    preserved = ''.join(lines[index] for index in proof['keep'])
    added = {line.split('=', 1)[0].strip() for line in preserved.splitlines()
             if '=' in line and not line.lstrip().startswith('#')}
    written = {line.split('=', 1)[0].strip() for line in block.splitlines() if '=' in line}
    if added & written:
        raise SystemExit(CONFLICT)
    return text[:proof['start']] + block + preserved + text[proof['end']:]


def write(path, before, after, writer):
    """Keep dotfile symlinks and refuse a changed file before replacing it."""
    path = Path(path)
    inspect(after)
    target = path.resolve()
    if read(path) != before or path.resolve() != target:
        raise SystemExit('Codex settings changed concurrently; retry the restore.')
    if after != before:
        writer(target, after, newline='')
    if path.resolve() != target or read(path) != after:
        raise SystemExit('Codex settings changed concurrently; run Check setup.')


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        print(json.dumps(_verified(request['text'], request.get('recorded'))))
    except (ValueError, KeyError, StopIteration):
        raise SystemExit(1) from None
