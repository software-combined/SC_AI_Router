"""Path scope for the expensive CI checks (Plan 156).

Usage:
  git diff --name-only BASE HEAD | python tools/ci_scope.py --installer
  python tools/ci_scope.py --installer-tests

`--installer` prints `installer=true|false`, whether a pull request can reach
the installer, its platform backends or its tests. Only then do the macOS and
Windows runners and the Python 3.9 import check run. `--installer-tests`
prints the module list those runners execute, so the workflows and this file
have one owner instead of two copies.

The path list also answers to config/installer-python-surface.txt: every file
the installer loads or runs on its own interpreter is installer scope, so a
change to `ai_router/winacl.py` or `tools/disable.py` cannot skip the native
checks.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SURFACE = ROOT / 'config' / 'installer-python-surface.txt'


def surface_paths(surface=SURFACE):
    """Every `<mode> <path>` entry in the installer surface file."""
    return tuple(line.split()[1] for line in surface.read_text().splitlines()
                 if line.strip() and not line.startswith('#'))


INSTALLER_PATHS = (
    'packaging/',
    '.github/actions/setup/',
    '.github/workflows/check.yml',
    '.github/workflows/release.yml',
    'config/installer-python-surface.txt',
    'tests/_platform.py',
    'tests/fakes.py',
    'tests/harness.py',
    'tests/install_fixtures.py',
    'tests/test_bootstrap.py',
    'tests/test_ci_scope.py',
    'tests/claude_profile_sync_fixtures.py',
    'tests/test_claude_desktop_policy.py',
    'tests/test_claude_profile_rules.py',
    'tests/test_install',
    'tests/test_installer_python39.py',
    'tests/test_interpreter_resolution.py',
    'tests/test_key_prompt.py',
    'tests/test_launchd',
    'tests/test_local_services.py',
    'tests/test_notice',
    'tests/test_packaging.py',
    'tests/test_platform_dispatch_order.py',
    'tests/test_systemd',
    'tests/test_update_announce.py',
    'tests/test_update_channel.py',
    'tests/test_windows_',
    'ai_router/key_dialog.py',
    'ai_router/key_prompt.py',
    'tools/check_installer_python39.py',
    'tools/ci_scope.py',
    'tools/verify_runtime_pins.py',
) + surface_paths()

INSTALLER_TESTS = (
    'tests.test_install',
    'tests.test_install_catalogue',
    'tests.test_install_config',
    'tests.test_install_key_window',
    'tests.test_install_lifecycle',
    'tests.test_install_state',
    'tests.test_bootstrap',
    'tests.test_ci_scope',
    'tests.test_claude_desktop_policy',
    'tests.test_claude_profile_rules',
    'tests.test_installer_python39',
    'tests.test_interpreter_resolution',
    'tests.test_key_prompt',
    'tests.test_launchd',
    'tests.test_launchd_guard',
    'tests.test_local_services',
    'tests.test_notice',
    'tests.test_notice_delivery',
    'tests.test_packaging',
    'tests.test_platform_dispatch_order',
    'tests.test_systemd',
    'tests.test_systemd_runtime',
    'tests.test_update_announce',
    'tests.test_update_channel',
    'tests.test_windows_acl',
    'tests.test_windows_backend',
    'tests.test_windows_portability',
)


def installer_scope(paths):
    """True when any changed path can affect the installer or its tests."""
    return any(path.startswith(INSTALLER_PATHS) for path in paths)


def main(argv):
    if '--installer-tests' in argv:
        print(' '.join(INSTALLER_TESTS))
        return 0
    if '--installer' in argv:
        paths = [line.strip() for line in sys.stdin if line.strip()]
        print('installer=%s' % ('true' if installer_scope(paths) else 'false'))
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
