"""Lossless receipt comparison; parsed values never leave the verifier process.

Only the single-line root assignments the installer writes are editable.
Other root assignments and comments survive outside the managed region.
Python 3.9 entrypoints use the managed interpreter for standard-library TOML.
"""
import hashlib
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
REASONS = {'receipt': 'damaged_receipt', 'markers': 'marker_conflict',
           'scope': 'unsupported_structure', 'shape': 'unsupported_structure',
           'connection': 'connection_changed', 'interpreter': 'parser_unavailable',
           'verifier': 'parser_failed'}


class OwnershipConflict(SystemExit):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(CONFLICT + ' [' + reason + ']')


def _reason(exc):
    return ('invalid_toml' if type(exc).__name__ == 'TOMLDecodeError'
            else REASONS.get(str(exc), 'ownership_conflict'))


def restore_evidence(entry, desktop_keys):
    """Reject malformed restore records before any attachment setting changes."""
    if not isinstance(entry, dict):
        raise OwnershipConflict('damaged_receipt')
    reviewer, desktop = entry.get('reviewer', {}), entry.get('desktop', {})
    reviewer = {} if reviewer is None else reviewer
    desktop = {} if desktop is None else desktop
    if not isinstance(reviewer, dict) or not isinstance(desktop, dict):
        raise OwnershipConflict('damaged_receipt')
    removed = reviewer.get('removed', [])
    if (not isinstance(removed, list) or any(not isinstance(line, str)
            or '\n' in line or '\r' in line for line in removed)):
        raise OwnershipConflict('damaged_receipt')
    for field in ('written', 'previous'):
        values = desktop.get(field, {})
        if not isinstance(values, dict) or set(values) - set(desktop_keys):
            raise OwnershipConflict('damaged_receipt')
    inserted = desktop.get('inserted_newline')
    if ('created' in desktop and not isinstance(desktop['created'], bool)
            or inserted is not None and (not isinstance(inserted, str)
                or len(inserted) != 64 or set(inserted) - set('0123456789abcdef'))):
        raise OwnershipConflict('damaged_receipt')
    return '\n'.join(removed)


def read(path):
    with Path(path).open(newline='') as stream:
        return stream.read()


def insert_lines(lines, index, added, record=None):
    """Insert recorded assignments without normalizing surviving lines."""
    ending = next((line[len(line.rstrip('\r\n')):] for line in lines
                   if line.endswith(('\r', '\n'))), '\n')
    if index and not lines[index - 1].endswith(('\r', '\n')):
        if record is not None:
            record['inserted_newline'] = hashlib.sha256(lines[index - 1].encode()).hexdigest()
        lines[index - 1] += ending
    lines[index:index] = [line + ending for line in added]


def restore_final_newline(text, record):
    """Trim only an inserted ending whose surviving line still matches its proof."""
    last = text.splitlines(keepends=True)[-1] if text else ''
    body = last.rstrip('\r\n')
    if (last != body and hashlib.sha256(body.encode()).hexdigest()
            == (record or {}).get('inserted_newline')):
        return text[:len(text) - len(last) + len(body)]
    return text


def render_line(line, rendered):
    """Replace a supported preference value, keeping its spacing and comment."""
    ending = line[len(line.rstrip('\r\n')):]
    head, _, tail = line.rstrip('\r\n').partition('=')
    value, separator, comment = tail.partition('#')
    leading = value[:len(value) - len(value.lstrip())]
    trailing = value[len(value.rstrip()):]
    return (head + '=' + leading + rendered.partition('=')[2].strip()
            + trailing + separator + comment + ending)


def parser_python():
    if PYTHON:
        return PYTHON
    home = Path(__file__).resolve().parents[3]
    candidates = (home / 'runtime/python/bin/python3.14',
                  home / 'runtime/python/python.exe')
    return next((str(path) for path in candidates if path.is_file()),
                shutil.which('python3.14'))


def _unique_picks(value):
    rows = value.splitlines(keepends=True)
    selected = {line.split('=', 1)[0].strip(): index for index, line in enumerate(rows)
                if '=' in line and line.split('=', 1)[0].strip() in PICKS}
    return ''.join(line for index, line in enumerate(rows)
                   if line.split('=', 1)[0].strip() not in selected
                   or selected[line.split('=', 1)[0].strip()] == index)


def _detached(text, recorded, restored):
    import tomllib
    _verified(recorded, recorded)
    expected = tomllib.loads(_unique_picks(recorded))
    actual, previous = tomllib.loads(text), tomllib.loads(restored)
    for key in CONNECTION_KEYS.intersection(expected.keys() | previous.keys()):
        if key == 'model_providers':
            owned = expected.get(key, {})
            prior = previous.get(key, {})
            current = actual.get(key, {})
            if not all(isinstance(value, dict) for value in (owned, prior, current)):
                raise ValueError('connection')
            for name in owned.keys() | prior.keys():
                if (name in prior and current.get(name) != prior[name]
                        or name not in prior and name in current):
                    raise ValueError('connection')
        elif (key in previous and actual.get(key) != previous[key]
              or key not in previous and key in actual):
            raise ValueError('connection')
    return {'detached': True}


def _verified(text, recorded=None, removing=False, restored='', absent=False):
    import tomllib
    if absent:
        _verified(recorded, recorded)
        if BEGIN in text or END in text:
            raise ValueError('markers')
        actual = tomllib.loads(text)
        if CONNECTION_KEYS.intersection(actual):
            raise ValueError('connection')
        return {'picks': [key for key in PICKS if key in actual]}
    if recorded is None:
        tomllib.loads(text)
        return {}
    if not isinstance(recorded, str) or not recorded:
        raise ValueError('receipt')
    if removing and BEGIN not in text and END not in text:
        return _detached(text, recorded, restored)
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
    expected = tomllib.loads(_unique_picks(recorded))
    actual = tomllib.loads(_unique_picks(region))
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


def inspect(text, recorded=None, removing=False, restored='', absent=False):
    try:
        if HAS_TOML:
            return _verified(text, recorded, removing, restored, absent)
        python = parser_python()
        if not python:
            raise ValueError('interpreter')
        result = run([python, str(Path(__file__).resolve()), '--verify'],
                     input=json.dumps({'text': text, 'recorded': recorded, 'removing': removing,
                                       'restored': restored, 'absent': absent}),
                     capture_output=True, text=True, timeout=15)
        if not result.stdout or len(result.stdout) > 65536:
            raise ValueError('verifier')
        try:
            reply = json.loads(result.stdout)
        except ValueError:
            raise ValueError('verifier') from None
        if not isinstance(reply, dict):
            raise ValueError('verifier')
        if result.returncode:
            reason = reply.get('error')
            allowed = set(REASONS.values()) | {'invalid_toml', 'ownership_conflict'}
            raise OwnershipConflict(reason if reason in allowed else 'parser_failed')
        if recorded is None and reply:
            raise ValueError('verifier')
        if absent:
            if (set(reply) != {'picks'} or not isinstance(reply['picks'], list)
                    or any(key not in PICKS for key in reply['picks'])):
                raise ValueError('verifier')
        elif recorded is not None and not (removing and reply == {'detached': True}):
            if (set(reply) != {'start', 'end', 'keep'}
                    or type(reply['start']) is not int or type(reply['end']) is not int
                    or not 0 <= reply['start'] < reply['end'] <= len(text)
                    or not isinstance(reply['keep'], list)
                    or any(type(index) is not int or not 0 <= index < len(text.splitlines())
                           for index in reply['keep'])):
                raise ValueError('verifier')
        return reply
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError) as exc:
        raise OwnershipConflict(_reason(exc)) from None


def region(text, recorded):
    proof = inspect(text, recorded)
    return text[proof['start']:proof['end']]


def replace(text, recorded, block, removing=False, restored=''):
    proof = inspect(text, recorded, removing, restored)
    if proof.get('detached'):
        return text
    lines = text.splitlines(keepends=True)
    preserved = ''.join(lines[index] for index in proof['keep'])
    added = {line.split('=', 1)[0].strip() for line in preserved.splitlines()
             if '=' in line and not line.lstrip().startswith('#')}
    written = {line.split('=', 1)[0].strip() for line in block.splitlines() if '=' in line}
    if added & written:
        raise OwnershipConflict('connection_changed')
    return text[:proof['start']] + block + preserved + text[proof['end']:]


def write(path, before, after, writer):
    """Keep dotfile symlinks and refuse a changed file before replacing it."""
    path = Path(path)
    inspect(after)
    target = path.resolve()
    if read(path) != before or path.resolve() != target:
        raise SystemExit('Codex settings changed concurrently; retry the restore.')
    if after != before:
        writer(target, after, newline='', expected=before)
    if path.resolve() != target or read(path) != after:
        raise SystemExit('Codex settings changed concurrently; run Check setup.')


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        print(json.dumps(_verified(request['text'], request.get('recorded'), request.get('removing', False),
                                   request.get('restored', ''), request.get('absent', False))))
    except (ValueError, KeyError, StopIteration) as exc:
        print(json.dumps({'error': _reason(exc)}))
        raise SystemExit(1) from None
