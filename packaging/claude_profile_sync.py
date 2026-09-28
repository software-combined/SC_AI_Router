"""Two-way session sync with active-winner precedence and per-session recovery."""
import contextlib
import importlib.util
import json
import os
import shutil
from pathlib import Path


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rules = _load('router_sync_rules', 'claude_profile_rules.py')
_records = _load('router_sync_records', 'claude_profile_records.py')
_bundle = _load('router_sync_bundle', 'claude_profile_bundle.py')
_transaction = _load('router_sync_transaction', 'claude_profile_transaction.py')
_service = _load('router_sync_service', 'service.py')
_history = _load('router_sync_history', 'claude_profile_history.py')
STORES = _records.STORES
PROFILE_NAMES = _records.PROFILE_NAMES
profile_roots = _records.profile_roots
_stage_union = _bundle.stage_union


def _report(failed=0, errors=(), pending=0):
    return dict(copied=0, replaced=0, unchanged=0, pending=pending,
                failed=failed, errors=list(errors))


def _transcript(record, bundle, env):
    cli = record.get('cliSessionId')
    if 'cliSessionId' not in record:
        return None
    if not _rules.safe_filename(cli):
        raise ValueError('required-transcript')
    config = Path(env.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude')))
    # Native continuations append to the shared CLI history; an imported bundle
    # is only a snapshot and otherwise hides every turn since the first copy.
    for root in (config / 'projects', bundle):
        _records.assert_ancestors(root)
        for path in sorted(root.rglob('*.jsonl')) if root.is_dir() else []:
            if (path.name != cli + '.jsonl' or _rules.skip(path.relative_to(root))
                    or not _records.safe_target(path, root) or not _rules.regular(path)):
                continue
            try:
                lines = [json.loads(line) for line in path.read_text(encoding='utf-8').split('\n') if line.strip()]
                if not lines or not all(isinstance(line, dict) for line in lines):
                    continue
                return path
            except (OSError, ValueError):
                continue
    raise ValueError('required-transcript')


def _choose(paths, namespace):
    candidates = [(path, _records.read_json(path)) for path in paths]
    if not candidates:
        return None, None
    active = [item for item in candidates if item[0].parent in (
        namespace[1], namespace[1] / 'agent')] if namespace else []
    pool = active or candidates
    if len(pool) == 1:
        return pool[0]
    if len({json.dumps(_rules.transcript_row(doc), sort_keys=True) for _, doc in pool}) == 1:
        return pool[0]
    raise ValueError('ambiguous-records')


def _repair_shared_history(record, env):
    cli = record.get('cliSessionId')
    if not _rules.safe_filename(cli):
        return
    root = Path(env.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))) / 'projects'
    _records.assert_ancestors(root)
    candidates = set()
    for path in root.rglob('*') if root.is_dir() else []:
        if (path.name == cli + '.jsonl' or
                path.name.startswith('.' + cli + '.jsonl.history-repair-')
                and path.name.endswith('.journal')):
            candidates.add(path.parent / (cli + '.jsonl'))
    for path in sorted(candidates):
        _records.assert_target(path, root)
        _history.repair_file(path)


def _sync_session(source_paths, source_root, target_root, target_store,
                  namespace, env, target_wins, protected=None, source_namespace=None):
    source_store = source_root / target_store.name
    source_record, source_doc = _choose(source_paths, source_namespace)
    identifier = _records.session_id(source_doc)
    target_paths = _records.group_records(target_store, account=namespace[0]).get(identifier, [])
    bundles = {p: _records.bundle_path(p, source_store if p in source_paths else target_store)
               for p in source_paths + target_paths}
    existing, existing_doc = _choose(target_paths, namespace)
    layout = existing if target_wins and existing else source_record
    layout_store = target_store if target_wins and existing else source_store
    container = Path(*layout.relative_to(layout_store).parts[2:-1])
    target = namespace[1] / container / (existing.name if existing else source_record.name)
    _records.assert_target(target, target_store)
    if target.exists() and target not in target_paths:
        raise ValueError('record-id-conflict')
    target_bundle = _records.bundle_path(target, target_store)
    if protected is not None:
        for path in target_paths:
            if (protected.get(path) != (_records.record_state(path),
                                       _transaction.tree_state(bundles[path]))):
                raise ValueError('target changed during sync')
    snapshot = _records.record_snapshot(source_paths + target_paths)
    bundle_snapshot = {p: _transaction.tree_state(p) for p in bundles.values()}
    duplicates = _bundle.duplicate_states(target_paths, target, bundles)
    # All target duplicates join the same union before any are retired.
    ordered_source = [source_record] + [p for p in source_paths if p != source_record]
    ordered_target = ([existing] + [p for p in target_paths if p != existing]) if existing else []
    ordered = (ordered_target + ordered_source if target_wins
               else ordered_source + ordered_target)
    inputs = [{'bundle': bundles[p], 'paths': (
        bundles[p], target_bundle,
        source_root if p in source_paths else target_root, target_root)}
        for p in ordered if p != target and bundles[p].exists()]
    paths = (bundles[source_record], target_bundle, source_root, target_root)
    existing_paths = ((bundles[existing], target_bundle, target_root, target_root)
                      if existing else None)
    text = _rules.project_record(source_doc, paths, existing_doc, target_wins, existing_paths)
    winner_doc = existing_doc if target_wins and existing_doc else source_doc
    winner_bundle = bundles[existing if target_wins and existing else source_record]
    # The caller holds both profile locks and has stopped Claude. Shared CLI
    # history is outside the bundle transaction and keeps its own originals.
    for path in source_paths + target_paths:
        _repair_shared_history(_records.read_json(path), env)
    transcript = _transcript(winner_doc, winner_bundle, env)
    # Required transcripts of every transferred record must also be valid.
    for path in source_paths + target_paths:
        _transcript(_records.read_json(path), bundles[path], env)
    before = {'record': _transaction.file_state(target),
              'bundle': _transaction.tree_state(target_bundle)}
    _rules.assert_clean_record(json.loads(text))
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    stage = _stage_union(target_bundle, target_wins, inputs, transcript,
                         source_root, target_root, transcript_paths=(
                             winner_bundle, target_bundle,
                             target_root if target_wins and existing else source_root, target_root))
    manifest = None
    try:
        _records.assert_record_snapshot(snapshot)
        if any(_transaction.tree_state(p) != old for p, old in bundle_snapshot.items()):
            raise ValueError('source changed during sync')
        unchanged = (target.exists() and json.loads(text) == _records.read_json(target)
                     and before['bundle'] is not None
                     and _transaction.tree_state(stage)[1:] == before['bundle'][1:])
        if unchanged and not duplicates:
            shutil.rmtree(stage)
            return 'unchanged'
        manifest = _transaction.write_pair_manifest(
            target_store, target, target_bundle, text, stage,
            before=before, duplicates=duplicates)
        _records.assert_record_snapshot(snapshot)
        _transaction.publish_pair(manifest, text)
        return 'replaced' if existing else 'copied'
    except Exception:
        if manifest is not None:
            _transaction.recover_store(target_store, errors=[], account=namespace[0])
        elif stage.exists():
            shutil.rmtree(stage)
        raise


def _sync_direction(source_root, target_root, env, target_wins=False,
                    blocked=None, protected=None, *, third_party_root=None):
    report = _report()
    blocked = set() if blocked is None else blocked
    for store in STORES:
        if (store, None) in blocked:
            continue
        source_store, target_store = source_root / store, target_root / store
        try:
            _records.assert_target(source_store, source_root)
            _records.assert_target(target_store, target_root)
            namespace = _records.resolve_namespace(
                target_store, target_root, third_party=target_root == third_party_root)
            source_namespace = _records.resolve_namespace(
                source_store, source_root, third_party=source_root == third_party_root)
            if namespace is None or source_namespace is None:
                report['pending'] += max(1, len(_records.group_records(source_store)))
                report['errors'].append('identity-unresolved')
                blocked.add((store, None))
                continue
        except (OSError, ValueError):
            report['failed'] += 1
            report['errors'].append('unsafe-store')
            blocked.add((store, None))
            continue
        errors, recovery_blocked = [], set()
        for root, account in ((source_store, source_namespace[0]), (target_store, namespace[0])):
            _transaction.recover_store(root, errors, recovery_blocked, account=account)
        report['failed'] += len(errors)
        report['errors'].extend(errors)
        if None in recovery_blocked:
            blocked.add((store, None))
        blocked.update((store, identifier) for identifier in recovery_blocked)
        source_groups = _records.group_records(source_store, account=source_namespace[0])
        target_groups = _records.group_records(target_store, account=namespace[0])
        invalid = len(_records.record_paths(source_store, True, account=source_namespace[0])) - sum(map(len, source_groups.values()))
        report['failed'] += invalid
        report['errors'].extend(['invalid-record'] * invalid)
        if (store, None) in blocked:
            continue
        _records.assert_target(namespace[1], target_root)
        namespace[1].mkdir(parents=True, exist_ok=True)
        for identifier in sorted(set(source_groups) | set(target_groups)):
            key = (store, identifier)
            if key in blocked:
                continue
            try:
                if identifier in source_groups:
                    outcome = _sync_session(source_groups[identifier], source_root, target_root,
                                            target_store, namespace, env, target_wins, protected,
                                            source_namespace)
                elif target_wins and any(path.parent in (namespace[1], namespace[1] / 'agent')
                                         for path in target_groups[identifier]):
                    # Capture a task created only in the active profile before
                    # the reverse pass shares it for the first time.
                    outcome = _sync_session(target_groups[identifier], target_root, target_root,
                                            target_store, namespace, env, True,
                                            source_namespace=namespace)
                else:
                    outcome = 'unchanged'
            except (OSError, ValueError, TypeError):
                blocked.add(key)
                report['failed'] += 1
                report['errors'].append('session-refused')
                continue
            report[outcome] += 1
    return report, blocked


def _store_snapshot(root):
    result = {}
    for store in STORES:
        try:
            paths = _records.record_paths(root / store)
        except (OSError, ValueError):
            continue
        for path in paths:
            try:
                result[path] = (_records.record_state(path),
                                _transaction.tree_state(_records.bundle_path(path, root / store)))
            except (OSError, ValueError):
                result[path] = None
    return result


def sync_profiles(home, winner, env=None):
    """Synchronize both profiles using the verified current active profile."""
    if winner not in PROFILE_NAMES:
        return _report(1, ['invalid-winner'])
    env = os.environ if env is None else env
    try:
        first, third = profile_roots(env, home=home)
        for root in (first, third):
            _records.assert_ancestors(root)
    except (OSError, ValueError):
        return _report(1, ['unsafe-profile'])
    if first.resolve() == third.resolve():
        return _report(1, ['identical-profiles'])
    if first.resolve() in third.resolve().parents or third.resolve() in first.resolve().parents:
        return _report(1, ['overlapping-profiles'])
    if not first.is_dir() or not third.is_dir():
        return _report(pending=1, errors=['profile-missing'])
    roots = {'1p': first, '3p': third}
    with contextlib.ExitStack() as locks:
        for root in sorted((first, third)):
            if not locks.enter_context(_service.install_lock(root, '.claude-profile-sync.lock')):
                return _report(1, ['profile-busy'])
        try:
            if _records._identity.bind_profile_accounts(home, first, third) is False:
                return _report(pending=1, errors=['account-binding-changed'])
        except (OSError, ValueError, TypeError):
            return _report(1, ['account-binding-refused'])
        inactive = roots['3p' if winner == '1p' else '1p']
        protected = _store_snapshot(inactive)
        first_pass, blocked = _sync_direction(inactive, roots[winner], env, target_wins=True,
                                              third_party_root=third)
        second_pass, _ = _sync_direction(roots[winner], inactive, env,
                                         blocked=blocked, protected=protected,
                                         third_party_root=third)
    result = {key: first_pass[key] + second_pass[key] for key in first_pass if key != 'errors'}
    result['errors'] = first_pass['errors'] + second_pass['errors']
    return result
