"""Shared installer fixtures (Plan 124).

Extracted verbatim from ``tests/test_install.py:24-137`` plus the
``static_fetch`` re-export (``:19``). ``test_install.py`` keeps only its
test classes; the ~20 importer modules now import from here. Any
behavioural difference from the originals is a defect.
"""
import hashlib
import importlib.util
import io
import json
import os
import shlex
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.fakes import LAUNCHD, static_fetch as _static_fetch

_ROOT = Path(__file__).resolve().parents[1]

static_fetch = _static_fetch


def real_bundle(tmp):
    """Build a real release bundle via packaging/release.py (slow; ~3s)."""
    feeddir = Path(tmp) / 'feed'
    feeddir.mkdir()
    spec = importlib.util.spec_from_file_location(
        'router_release', _ROOT / 'packaging' / 'release.py')
    release_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release_mod)
    release_mod.main(['--out', str(feeddir)])
    tarball = next(iter(feeddir.glob('*.tar.gz')))
    blob = tarball.read_bytes()
    with tarfile.open(tarball, mode='r') as tar:
        manifest = json.loads(tar.extractfile('MANIFEST.json').read())
    return manifest['version'], _static_fetch(
        {'version': manifest['version'], 'url': 'file:///bundle.tar.gz',
         'sha256': hashlib.sha256(blob).hexdigest(), 'min_python': '3.14'}, blob), blob, manifest


def install_mod_factory():
    spec = importlib.util.spec_from_file_location('router_install', _ROOT / 'packaging' / 'install.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # This existing rig exercises launchd on every host. Linux lifecycle
    # tests explicitly select linux and use the same installer seams.
    module.PLATFORM = 'darwin'
    # Installer tests must never open the real client chooser. Tests that
    # exercise the chooser replace these seams with their own fake dialog.
    module._client_choice._dialog.tool = lambda *args, **kwargs: None
    module._client_choice._dialog.ask = _unexpected_dialog
    module._delivery.close_assistants = _unexpected_dialog
    module._updater._offer_notices = lambda *_: None
    # Nor build or remove the real Switch Codex app: its location was named
    # before any test moved HOME. tests/test_codex_switch_app.py drives it.
    module._client_choice._app.sync = lambda *args, **kwargs: None
    # The served model list is a loopback boundary; unit fixtures stay offline.
    module._operator.listing = lambda state: None
    return module


def _unexpected_dialog(*args, **kwargs):
    raise AssertionError('real client chooser reached a test')


install_mod = install_mod_factory()


def tarball(files=(), links=()):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tar:
        for name, data in files:
            raw = data if isinstance(data, bytes) else data.encode()
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))
        for name, target in links:
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tar.addfile(info)
    return buf.getvalue()


def ok_run(cmd, **kwargs):
    if '-c' in cmd:
        return SimpleNamespace(returncode=0, stdout='3 14\n/opt/homebrew/bin/python3.14\n',
                               stderr='')
    answer = systemd_show(cmd)
    if answer is not None:
        return answer
    # launchctl goes through the stateful domain model: a fake that answered
    # `print` with rc 0 for a booted-out label is what let the bootout/bootstrap
    # defect reach a release.
    answer = LAUNCHD(cmd, **kwargs)
    if answer is not None:
        return answer
    return SimpleNamespace(returncode=0, stdout='', stderr='')


def systemd_show(cmd):
    """The loaded-command boundary; drift tests replace this with a stale reply."""
    if cmd[:3] != ['systemctl', '--user', 'show']:
        return None
    config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    unit = config / 'systemd/user' / cmd[3]
    lines = unit.read_text().splitlines() if unit.exists() else []
    command = next((line.partition('=')[2] for line in lines if line.startswith('ExecStart=')), '')
    argv = [value.replace('%%', '%').replace('$$', '$') for value in shlex.split(command)]
    output = '{ path=%s ; argv[]=%s ; }' % (argv[0], ' '.join(argv)) if argv else ''
    return SimpleNamespace(returncode=0, stdout=output, stderr='')


def craft_bundle(version):
    """Crafted install bundle + feed doc (bytes only, no release build)."""
    from tests.fakes import install_payloads
    files = install_payloads(version)
    manifest = {'version': version, 'files':
                {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    blob = tarball(files=[('MANIFEST.json', json.dumps(manifest)), *files.items()])
    latest = {'version': version, 'url': 'file:///bundle.tar.gz',
              'sha256': hashlib.sha256(blob).hexdigest(), 'min_python': '3.14'}
    return blob, latest


_SEAMS = ('run', 'health', 'wait_version', 'self_test',
          'write_catalogue', 'fetch_feed', 'feed_serial')


def patch_attrs(test, **overrides):
    test.addCleanup(LAUNCHD.reset)
    LAUNCHD.reset()
    # Real launchd settle windows are minutes long; tests must never wait on
    # wall-clock time, and must never fall back to a real time.sleep.
    for mod in (install_mod, install_mod._svc):
        for name, value in (('UNLOAD_TIMEOUT_S', 2), ('LOAD_TIMEOUT_S', 2),
                            ('_sleep', lambda *_a, **_k: None)):
            if hasattr(mod, name):
                test.addCleanup(setattr, mod, name, getattr(mod, name))
                setattr(mod, name, value)
    for name, value in overrides.items():
        if name not in _SEAMS and not hasattr(install_mod, name):
            raise AttributeError(f'unknown installer seam: {name}')
        test.addCleanup(setattr, install_mod, name, getattr(install_mod, name))
        setattr(install_mod, name, value)
        # Call sites sync from install_mod._svc on entry; mirror there too.
        if hasattr(install_mod._svc, name):
            test.addCleanup(setattr, install_mod._svc, name,
                            getattr(install_mod._svc, name))
            setattr(install_mod._svc, name, value)


def run_install(test, tmp, home, fake_fetch, fake_run):
    args = install_mod.build_parser().parse_args(
        ['--feed', 'file:///latest.json', '--home', str(home)])
    env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'test-key',
           'ROUTER_NO_KEY_WINDOW': '1'}
    with mock.patch.dict(os.environ, env):
        test.assertEqual(
            install_mod.do_install(args, _fetch=fake_fetch, _run=fake_run), 0)
    return args, env


# Underscore aliases for the modules migrated from test_install imports.
_real_bundle = real_bundle
_install_mod = install_mod_factory
_tarball = tarball
_ok_run = ok_run
_craft_bundle = craft_bundle
_patch_attrs = patch_attrs
_run_install = run_install


__all__ = ['static_fetch', 'real_bundle', 'install_mod_factory',
           'install_mod', 'tarball', 'ok_run', 'systemd_show', 'craft_bundle',
           'patch_attrs', 'run_install', '_real_bundle', '_install_mod',
           '_tarball', '_ok_run', '_craft_bundle', '_patch_attrs',
           '_run_install', '_SEAMS']


def uninstall_home(tmp):
    """Staged home with one installed release, pointer current, and plists."""
    home = Path(tmp) / 'home'
    rel = home / 'releases' / '1.0.0'
    (rel / 'tools').mkdir(parents=True)
    (rel / 'tools' / 'disable.py').write_text('# stub\n')
    (home / 'current').write_text('1.0.0\n')
    config = Path(tmp) / 'fakehome/.codex/config.toml'
    config.parent.mkdir(parents=True)
    block = install_mod._codex_config.build_block(
        home, {'port': 4321, 'token': 'synthetic'}, 'subscription')
    config.write_text(block)
    (home / 'activation.json').write_text(json.dumps(
        {'config_path': str(config), 'inserted_block': block}))
    agents = Path(tmp) / 'fakehome' / 'Library' / 'LaunchAgents'
    agents.mkdir(parents=True)
    return home, agents
