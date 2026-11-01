"""Platform guards for tests that exercise OS-specific behaviour.

The install / update / service layer targets macOS ``launchd`` and Linux
``systemd`` (see ``README.md`` and ``AGENTS.md``): it shells out to
``launchctl`` / ``systemctl`` and relies on ``os.getuid``, ``fcntl`` and
privileged symlinks, none of which exist on Windows. A second, smaller group
asserts POSIX permission bits (``chmod 600``) that Windows cannot express in
``st_mode``. Both groups are skipped on Windows so ``python -m unittest
discover`` runs green there; the cross-platform router core stays covered.
"""
import os
import stat
import unittest

unix_only = unittest.skipIf(
    os.name == 'nt',
    'exercises the macOS launchd / Linux systemd install & service layer')

requires_posix_perms = unittest.skipUnless(
    os.name == 'posix',
    'asserts POSIX permission bits (chmod 600) not expressible on Windows')

ON_WINDOWS = os.name == 'nt'


def symlink_or_skip(source, destination, *, target_is_directory=False):
    """Exercise real links unless Windows denies the required privilege."""
    try:
        destination.symlink_to(source, target_is_directory=target_is_directory)
    except OSError as exc:
        if getattr(exc, 'winerror', None) == 1314:
            raise unittest.SkipTest('Windows symlink privilege is unavailable') from exc
        raise


def assert_owner_only(test, path):
    """Assert `path` is owner-only in the way this OS can express it.

    POSIX carries the exact 0600 bits, so the assertion is precise there. On
    Windows ``st_mode`` cannot hold POSIX bits (a written file reports 0666),
    and the real owner-only guarantee is an ``icacls`` ACL grant checked by
    the Windows key-file tests; here we assert the file exists and is
    readable and writable by this process, which is what the caller relies
    on across platforms.
    """
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if ON_WINDOWS:
        test.assertTrue(os.path.isfile(path), path)
        test.assertTrue(os.access(path, os.R_OK | os.W_OK), path)
    else:
        test.assertEqual(mode, 0o600, oct(mode))
