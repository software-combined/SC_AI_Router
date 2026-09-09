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
import unittest

unix_only = unittest.skipIf(
    os.name == 'nt',
    'exercises the macOS launchd / Linux systemd install & service layer')

requires_posix_perms = unittest.skipUnless(
    os.name == 'posix',
    'asserts POSIX permission bits (chmod 600) not expressible on Windows')
