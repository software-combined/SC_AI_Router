"""Print only local attachment ownership classifications; never configuration contents."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location('router_classify_' + name,
                                                ROOT / 'packaging' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REASONS = frozenset(('damaged_receipt', 'marker_conflict', 'unsupported_structure',
    'connection_changed', 'parser_unavailable', 'parser_failed', 'invalid_toml',
    'ownership_conflict', 'duplicate_keys', 'invalid_json', 'unreadable'))


def classify(home):
    """Use the repair/removal proof without applying it or making network requests."""
    owner, removal = _load('codex_config'), _load('client_removal')
    home = Path(home)
    result = dict(schema=1, receipt='missing', clients={})
    try:
        if owner.receipt_path_for(home).is_symlink():
            raise ValueError('damaged_receipt')
        raw = removal.read(owner.receipt_path_for(home))
        if raw is None:
            return result
        doc = removal._json.document(raw)
        if not (doc.get('version') == 2 and isinstance(doc.get('clients'), dict)
                or isinstance(doc.get('config_path'), str) and isinstance(doc.get('inserted_block'), str)):
            raise ValueError('damaged_receipt')
        entries = owner.read_receipt(home)['clients']
        if set(entries) - removal.LABELS.keys():
            raise ValueError('damaged_receipt')
        result['receipt'] = 'readable'
    except (OSError, ValueError, TypeError, KeyError):
        result['receipt'] = 'conflict'
        result['reason'] = 'damaged_receipt'
        return result
    for name, entry in entries.items():
        try:
            if name == 'codex':
                owner.removal_plan(removal.entry_path(entry), entry)
            else:
                removal.json_plan(home, name, entry)
            result['clients'][name] = dict(classification='owned')
        except (OSError, ValueError, TypeError, KeyError, SystemExit) as exc:
            reason = 'unreadable' if isinstance(exc, OSError) else getattr(exc, 'reason', str(exc))
            result['clients'][name] = dict(classification='conflict',
                reason=reason if reason in REASONS else 'ownership_conflict')
    return result


def main(argv=None):
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path(os.environ.get(
        'ROUTER_HOME', str(Path.home() / '.codex/mixed-model-router'))))
    args = parser.parse_args(argv)
    print(json.dumps(classify(args.home.expanduser()), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
