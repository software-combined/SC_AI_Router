"""One backend per OS behind a single interface (Plan 056).

`select()` returns a backend or None; None means unsupported, never macOS.
Backends own service lifecycle only: plists/units, reload, restart, stop,
updater job, uninstall. Shared feed/verify/config logic stays in install.py.
Loaded via the installer's file-based import pattern, never
`import packaging.platforms`, so installed bundles keep working without a
`packaging` distribution.
"""
from pathlib import Path

import importlib.util


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_darwin = None
_linux = None
_windows = None


def _darwin_mod():
    global _darwin
    if _darwin is None:
        _darwin = _load('router_platform_darwin', 'darwin.py')
    return _darwin


def _linux_mod():
    global _linux
    if _linux is None:
        _linux = _load('router_platform_linux', 'linux.py')
    return _linux


def _windows_mod():
    global _windows
    if _windows is None:
        _windows = _load('router_platform_windows', 'windows.py')
    return _windows


def select(platform, svc, run):
    """Backend for this platform, or None when unsupported.

    `svc` is the shared service helper module; `run` is the patchable
    subprocess seam. Bound per call so test seams keep working.
    """
    if platform == 'darwin':
        return _darwin_mod().Backend(svc, run)
    if platform == 'linux':
        return _linux_mod().Backend(svc, run)
    if platform == 'win32':
        return _windows_mod().Backend(svc, run)
    return None
