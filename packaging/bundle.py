"""Bundle verify/unpack/install/prune helpers, split from install.py (Plan 130).

Owns release verification and publication: checksum, manifest and identity
checks, the extraction smoke test, credential collection, bundle install,
catalogue seeding, release pruning and rollback activation. install.py
keeps orchestration (platform dispatch, clients) and forwards its test
seams explicitly, so _patch_attrs swaps keep working. Runs on Python 3.9+
like the installer. Loaded via service.load(), never `import packaging.bundle`,
so installed bundles keep working without a `packaging` distribution.
"""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib.util  # noqa: E402
# Bootstrap loader (Plan 123 exception): service must be spec-loaded before
# service.load() exists, so this single bootstrap copy stays.
_spec = importlib.util.spec_from_file_location(
    'packaging.service',
    Path(__file__).resolve().parent / 'service.py')
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)

# Seam globals (Plan 130): install.py mirrors its swaps here via
# bind_seams() on every _sync_seams() pass, so the bundle call sites read
# the patched fakes. Direct bundle use keeps the _svc defaults.
run = _svc.run
safe_extract = _svc.safe_extract
install_launcher = _svc.install_launcher
swap_current = _svc.swap_current


def bind_seams(**overrides):
    for name, value in overrides.items():
        if name not in ('run', 'safe_extract', 'install_launcher',
                        'swap_current'):
            raise AttributeError(f'unknown bundle seam: {name}')
        globals()[name] = value


def verify_sha256(data, want):
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise SystemExit('bundle checksum mismatch')
    return True


def newer(a, b):
    return tuple(int(x) for x in a.split('.')) > tuple(int(x) for x in b.split('.'))


def check_manifest(release_dir, manifest):
    for name, want in manifest['files'].items():
        got = hashlib.sha256((release_dir / name).read_bytes()).hexdigest()
        if got != want:
            raise SystemExit('bundle manifest mismatch: ' + name)


def check_identity(version, manifest_doc, release_dir):
    """Fail closed when feed, manifest and bundled marker disagree.

    The updater waits on the feed version and /health reports the manifest
    version, so any mismatch strands the install in a failed-health loop.
    """
    manifest_version = manifest_doc.get('version')
    try:
        marker = (release_dir / 'packaging' / 'VERSION').read_text().strip()
    except OSError:
        marker = None
    if manifest_version != version or marker != version:
        raise SystemExit(
            f'release identity mismatch: feed={version} '
            f'manifest={manifest_version} marker={marker}')


def self_test(python, release_dir, run=None):
    if run is None:
        run = globals()['run']
    # Bundle smoke: the runtime import closure must load from the extraction.
    # Full discover cannot run here: repo tests reference files outside the bundle.
    result = run([python, '-c',
                 'from ai_router import catalogue, registry; assert registry.MODELS'],
                 cwd=str(release_dir), capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise SystemExit('bundle self-test failed')


def _clear_current(home):
    current = home / 'current'
    try:
        if current.is_symlink() or current.is_file():
            current.unlink()
    except OSError:
        pass


def ensure_credentials(home, state, env=None, protect=None, provider_keys=None):
    """Prompt for any missing external-provider key, then stop.

    One key file per provider (Plan 141): the first provider without a
    resolvable key gets an owner-only empty file and the instructions to
    paste into it. Providers that resolve are skipped, so a second
    provider's key is collected without disturbing the first.
    """
    env = os.environ if env is None else env
    if provider_keys is None:
        provider_keys = globals()['provider_keys']
    provider_keys().ensure(home, state, env, protect)


def provider_keys():
    """The shared per-provider key walk (Plan 141), spec-loaded for 3.9."""
    module = _svc.load(
        'router_provider_keys', Path(__file__).resolve().parent / 'provider_keys.py')
    module.bind(_svc.load(
        'router_provider_defs',
        Path(__file__).resolve().parents[1] / 'ai_router' / 'provider_defs.py'))
    return module


def install_bundle(home, version, tarball, manifest_doc, python,
                   self_test=None, write_catalogue=None, safe_extract=None,
                   install_launcher=None, swap_current=None):
    if self_test is None:
        self_test = globals()['self_test']
    if write_catalogue is None:
        write_catalogue = globals()['write_catalogue']
    if safe_extract is None:
        safe_extract = globals()['safe_extract']
    if install_launcher is None:
        install_launcher = globals()['install_launcher']
    if swap_current is None:
        swap_current = globals()['swap_current']
    releases = home / 'releases'
    releases.mkdir(parents=True, exist_ok=True)
    partial = releases / (version + '.partial')
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir()
    safe_extract(tarball, partial)
    try:
        check_manifest(partial, manifest_doc)
        check_identity(version, manifest_doc, partial)
        self_test(python, partial)
        write_catalogue(home, partial, python)
    except (SystemExit, OSError):
        shutil.rmtree(partial, ignore_errors=True)
        raise
    final = releases / version
    if final.exists():
        shutil.rmtree(final)
    partial.rename(final)
    install_launcher(home, final)
    install_home_readme(home, final)
    previous = swap_current(home, final)
    return previous


def install_home_readme(home, release_dir):
    """Keep the page beside the state directory the one this release ships.

    A host that kept whatever its first install wrote went on describing a
    router it no longer ran, and that page is the first thing a person reads
    in their own install. The launchers beside it fail closed; this page must
    not, so it is best-effort and a release that predates the bundled page
    keeps the existing copy. The tmp is cleared first for the same reason
    `service._install_home_file` clears its own: a planted symlink there would
    otherwise aim the write at whatever it points to.
    """
    source = release_dir / 'README.md'
    tmp = home / 'README.md.tmp'
    try:
        if not source.is_file():
            return
        if tmp.is_symlink() or tmp.is_file():
            tmp.unlink()
        elif tmp.exists():
            shutil.rmtree(tmp)
        shutil.copyfile(source, tmp)
        os.replace(tmp, home / 'README.md')
    except OSError:
        return


def write_catalogue(home, release_dir, python, run=None):
    if run is None:
        run = globals()['run']
    # Seed the picker file the config block points at; refresh owns it after.
    result = run([python, '-m', 'ai_router.catalogue', '--merge', str(home / 'mixed-models.json')],
                 cwd=str(release_dir), capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit('catalogue merge failed')


def _release_key(name):
    try:
        return [int(x) for x in name.split('.')]
    except ValueError:
        return None  # operator dirs sort out of version pruning entirely


def prune_releases(home, *keep):
    """Keep current plus two prior verified releases for rollback depth."""
    names = [p.name for p in (home / 'releases').glob('*') if p.is_dir()
             and not p.name.endswith('.partial')]
    versions = sorted((n for n in names if _release_key(n) is not None),
                      key=_release_key, reverse=True)
    for stale in versions[3:]:
        if stale not in keep:
            shutil.rmtree(home / 'releases' / stale, ignore_errors=True)


def do_rollback(args, *, platform_backend, restart_router, wait_version,
                current_version, swap_current):
    """Point current at a previously installed release and verify it serves.
    Only releases still present under home/releases can be restored; the feed
    carries the latest bundle only, so there is nothing to download a
    rollback from. The feed serial is never touched.
    """
    home = Path(args.home).expanduser()
    if args.dry_run:
        print(f'would roll back to {args.version} under {home}')
        return 0
    platform_backend().check(home)
    target = home / 'releases' / args.version
    if not target.is_dir() or not (target / 'packaging' / 'VERSION').exists():
        raise SystemExit(f'version {args.version} is not installed under {home}')
    current = current_version(home)
    if current == args.version:
        print(f'up to date {current}')
        return 0
    try:
        state = json.loads((home / 'mixed-router-state.json').read_text())
    except (OSError, ValueError):
        raise SystemExit(f'router state is missing or unreadable under {home}')
    previous = swap_current(home, target)
    restart_router(home)
    if not wait_version(state, args.version):
        if previous is not None:
            swap_current(home, home / 'releases' / previous)
            print(f'rollback to {args.version} failed health check; restored {previous}')
        else:
            _clear_current(home)
            print(f'rollback to {args.version} failed health check; no previous release')
        restart_router(home)
        raise SystemExit(1)
    # After the health gate, so the page never describes a release that was
    # rolled back away from.
    install_home_readme(home, target)
    print(f'rolled back to {args.version}; health ok; restart Codex to load the router')
    return 0
