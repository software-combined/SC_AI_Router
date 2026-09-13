"""Prove the installer surface runs on the interpreter that runs the installer.

The installer runs on Python 3.9+ while the router needs 3.14 (Plan 061), so
CI runs this under a real 3.9 (Plan 156). `load` files in
config/installer-python-surface.txt are imported by path the way the installer
loads them -- in a child process with a scratch HOME, ROUTER_HOME and PATH, so
a file that reaches outside the repository cannot touch the host. `parse`
files are compile-checked only: tools/disable.py detaches the live router when
it runs (2026-09-13 incident) and the installed-tree launchers act at import
by design.

There is deliberately no sys.modules leak test for 3.14-only stdlib: under a
real 3.9 such an import fails the load outright, and under a 3.14 smoke run
the stdlib imports e.g. `compression` itself, so the signal would be false.

Usage: python3.9 tools/check_installer_python39.py [--root REPO]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SURFACE = 'config/installer-python-surface.txt'
MODES = ('load', 'parse')
# Commands a surface file could reach for that would change the host; the
# child gets a no-op shim first on PATH. Absolute paths are out of scope for
# a repository-owned check and are covered by the load/parse split.
SHIMMED_COMMANDS = ('launchctl', 'systemctl', 'schtasks', 'icacls', 'osascript')

_CHILD = r'''
import importlib.util, json, sys
from pathlib import Path

root, files = Path(sys.argv[1]), json.loads(sys.argv[2])
loaded, failures = [], []
for rel in files:
    try:
        name = 'installer_surface_' + rel.rsplit('.', 1)[0].replace('/', '_')
        spec = importlib.util.spec_from_file_location(name, root / rel)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        loaded.append(rel)
    except (Exception, SystemExit) as exc:
        failures.append('%s: %s: %s' % (rel, type(exc).__name__, exc))
leaked = sorted(name for name in sys.modules
                if name.split('.')[0] in ('ai_router', 'codex_router'))
leaves = set()
for module in list(sys.modules.values()):
    filename = getattr(module, '__file__', None)
    if filename and 'ai_router' in Path(filename).parts:
        leaves.add(Path(filename).name)
print('CHECK-JSON ' + json.dumps(
    {'loaded': loaded, 'failures': failures,
     'leaked': leaked, 'leaves': sorted(leaves)}))
'''


def read_surface(root):
    """[(mode, rel)] from the surface file; malformed lines are problems."""
    entries, problems = [], []
    try:
        text = (root / SURFACE).read_text()
    except OSError as exc:
        return [], ['cannot read %s: %s' % (SURFACE, exc)]
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) != 2 or parts[0] not in MODES:
            problems.append('%s:%d: expected "<load|parse> <path>"' % (SURFACE, number))
            continue
        entries.append((parts[0], parts[1]))
    if not entries:
        problems.append('%s lists no files' % SURFACE)
    return entries, problems


def syntax_problems(root, entries):
    """Compile every listed file; parse-only entries are checked here."""
    out = []
    for _mode, rel in entries:
        try:
            source = (root / rel).read_text()
        except OSError as exc:
            out.append('cannot read %s: %s' % (rel, exc))
            continue
        try:
            compile(source, rel, 'exec')
        except SyntaxError as exc:
            out.append('%s:%s: %s' % (rel, exc.lineno, exc.msg))
    return out


def write_shims(directory):
    """POSIX no-op stand-ins for host-mutating commands, for the child PATH."""
    if os.name == 'nt':
        return
    for name in SHIMMED_COMMANDS:
        path = directory / name
        path.write_text('#!/bin/sh\nexit 0\n')
        path.chmod(0o700)


def contained_import(root, loads):
    """Import the load set in a scratch child; return (report, result)."""
    scratch = Path(tempfile.mkdtemp(prefix='installer-python-'))
    try:
        shims = scratch / 'bin'
        shims.mkdir()
        write_shims(shims)
        for name in ('home', 'router-home', 'tmp'):
            (scratch / name).mkdir()
        env = {key: value for key, value in os.environ.items()
               if key not in ('PYTHONPATH', 'PYTHONSTARTUP',
                              'ROUTER_LIVE_RUN', 'ROUTER_RESTORE_ONLY')}
        env['HOME'] = str(scratch / 'home')
        env['ROUTER_HOME'] = str(scratch / 'router-home')
        env['TMPDIR'] = str(scratch / 'tmp')
        env['PATH'] = str(shims) + os.pathsep + env.get('PATH', '')
        result = subprocess.run(
            [sys.executable, '-I', '-B', '-c', _CHILD, str(root), json.dumps(loads)],
            cwd=str(scratch), env=env, capture_output=True, text=True)
        marker = 'CHECK-JSON '
        for line in reversed(result.stdout.splitlines()):
            if line.startswith(marker):
                return json.loads(line[len(marker):]), result
        return None, result
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]),
                        help='repository root to check')
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    entries, problems = read_surface(root)
    problems += syntax_problems(root, entries)
    loads = [rel for mode, rel in entries if mode == 'load']
    parsed = [rel for mode, rel in entries if mode == 'parse']
    report, result = contained_import(root, loads)
    if report is None:
        problems.append('the import child produced no report (exit %d)\n%s'
                        % (result.returncode, (result.stderr or '').strip()[-2000:]))
        report = {'loaded': [], 'failures': [], 'leaked': [], 'leaves': []}
    problems += report['failures']
    if report['leaked']:
        problems.append('the router package was imported: %s'
                        % ', '.join(report['leaked']))
    expected = {rel.rsplit('/', 1)[1] for rel in loads if rel.startswith('ai_router/')}
    unexpected = sorted(set(report['leaves']) - expected)
    if unexpected:
        problems.append('unlisted runtime modules loaded: %s' % ', '.join(unexpected))
    for rel in loads:
        if rel not in report['loaded'] and not any(
                failure.startswith(rel + ':') for failure in report['failures']):
            problems.append('%s was not loaded' % rel)
    for problem in problems:
        print('FAIL %s' % problem)
    print('installer-python: python=%s loaded=%d parsed=%d failures=%d'
          % (sys.version.split()[0], len(report['loaded']), len(parsed), len(problems)))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
