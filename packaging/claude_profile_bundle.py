"""Stage one screened union before publishing or retiring any session copy."""
import importlib.util
import os
import shutil
import uuid
from pathlib import Path


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_transaction = _load('router_bundle_transaction', 'claude_profile_transaction.py')
_rules = _load('router_bundle_rules', 'claude_profile_rules.py')
_records = _load('router_bundle_records', 'claude_profile_records.py')
_history = _load('router_bundle_history', 'claude_profile_history.py')


def assert_target(path):
    _records.assert_ancestors(path)
    if path.exists() and not path.is_dir():
        raise ValueError('unsafe target bundle')


def entries(root, include_skipped=False):
    """Never follow an irregular child. The caller separately blocks retirement."""
    files, directories, unsafe = {}, {}, []
    assert_target(root)
    for current, dirs, names in os.walk(root, followlinks=False):
        parent = Path(current)
        for name in list(dirs) + names:
            path = parent / name
            relative = path.relative_to(root)
            safe = _records.safe_target(path, root)
            if not safe or (not path.is_dir() and not _rules.regular(path)):
                unsafe.append(relative)
                if name in dirs:
                    dirs.remove(name)
                continue
            if not include_skipped and _rules.skip(relative):
                if name in dirs:
                    dirs.remove(name)
                continue
            (directories if path.is_dir() else files)[relative.as_posix()] = path
    return files, directories, unsafe


def _files(root, include_skipped=False):
    return entries(root, include_skipped)[0]


def stage_union(target_bundle, target_wins, inputs, transcript,
                source_root=None, target_root=None, transcript_paths=None):
    target_bundle = Path(target_bundle)
    target_files, target_dirs, unsafe = entries(target_bundle, True)
    maps = [(target_files, target_dirs, None)] if target_wins else []
    for item in inputs:
        files, directories, bad = entries(item['bundle'])
        unsafe.extend(bad)
        maps.append((files, directories, item['paths']))
    if transcript is not None:
        relative = (Path('.claude/projects/session') / transcript.name).as_posix()
        maps.insert(0, ({relative: transcript}, {},
                     transcript_paths or (None, target_bundle, source_root, target_root)))
    if not target_wins:
        maps.append((target_files, target_dirs, None))
    if unsafe:
        raise ValueError('unsafe bundle artifact')
    files, directories = {}, {}
    for file_map, dir_map, paths in maps:
        for name, source in file_map.items():
            files.setdefault(name, (source, paths))
        for name, source in dir_map.items():
            directories.setdefault(name, source)
    if files.keys() & directories.keys():
        raise ValueError('bundle shape conflict')
    for name in files.keys() | directories.keys():
        if any(parent.as_posix() in files for parent in Path(name).parents):
            raise ValueError('bundle shape conflict')
    stage = target_bundle.with_name(target_bundle.name + '.tmp-' + uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    try:
        _transaction._publish.private(stage)
        for name, source in sorted(directories.items(), key=lambda row: len(Path(row[0]).parts)):
            destination = stage / name
            destination.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.chmod(source.stat().st_mode & 0o777)
        for name, (source, paths) in sorted(files.items()):
            before = _transaction.file_state(source)
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if paths is None:
                shutil.copy2(source, destination)
            else:
                mode = source.stat().st_mode & 0o777
                if name in target_files:
                    mode &= target_files[name].stat().st_mode & 0o777
                conversation = transcript is not None and source.name == transcript.name
                _rules.copy_file(source, destination, paths, mode=mode, conversation=conversation)
            if source == transcript:
                text = destination.read_text(encoding='utf-8')
                projected = _history.portable_history(text)
                if projected != text:
                    destination.write_text(projected, encoding='utf-8')
            if _transaction.file_state(source) != before:
                raise ValueError('source changed during sync')
        _transaction._publish.flush(stage)
        return stage
    except Exception:
        shutil.rmtree(stage)
        raise


def duplicate_states(paths, keep, bundles=None):
    result = []
    for path in paths:
        if path == keep:
            continue
        bundle = bundles[path] if bundles is not None else path.with_suffix('')
        files, directories, unsafe = entries(bundle, True)
        if unsafe or any(_rules.skip(Path(name)) for name in files.keys() | directories.keys()):
            raise ValueError('excluded duplicate artifact')
        result.append({'record': path, 'bundle': bundle, 'before': {
            'record': _transaction.file_state(path), 'bundle': _transaction.tree_state(bundle)}})
    return result
