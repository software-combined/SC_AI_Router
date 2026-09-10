"""Install-once global starter instructions (no vault, no personal data).

Owns the Dev/General starter templates and one create-only install used by
the setup window. Updates and uninstall never touch global instructions:
the owner's file is authoritative the moment it exists.
"""
from pathlib import Path

PROFILES = ('general', 'dev')


def template(profile):
    """Starter text for `profile`; unknown names fall back to general."""
    name = 'agents_dev.txt' if profile == 'dev' else 'agents_general.txt'
    return (Path(__file__).with_name(name)).read_text()


def target(codex_home=None):
    """Active global instructions file: non-empty override wins, else AGENTS.md."""
    home = Path(codex_home) if codex_home is not None else Path.home() / '.codex'
    override = home / 'AGENTS.override.md'
    try:
        if override.exists() and override.read_text().strip():
            return override
    except OSError:
        pass
    return home / 'AGENTS.md'


def install(profile, codex_home=None):
    """Write the chosen starter once; never touch an existing file.

    Returns 'profile:path' on success, 'kept' when an existing file (or a
    symlink, whose target lives outside this contract) was left alone, or
    'skipped' when the write failed and setup must continue without one.
    """
    import os
    if profile not in PROFILES:
        profile = 'general'
    try:
        path = target(codex_home)
        if path.is_symlink():
            return 'kept'
        try:
            existing = path.read_text()
        except FileNotFoundError:
            existing = ''
        if existing.strip():
            return 'kept'
        path.parent.mkdir(parents=True, exist_ok=True)
        text = template(profile)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            # Lost the create race: the file appeared after the check, so
            # re-read once and keep whatever is there now.
            try:
                if path.read_text().strip():
                    return 'kept'
            except OSError:
                return 'skipped'
            return 'kept'
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
        return '%s:%s' % (profile, path)
    except OSError:
        return 'skipped'


def revert(installed):
    """Remove a starter this setup run just wrote; ignore anything else."""
    try:
        profile, _, name = installed.partition(':')
        if profile not in PROFILES or not name:
            return
        path = Path(name)
        if path.read_text() == template(profile):
            path.unlink()
    except OSError:
        pass


_DESCRIBE = {'dev': 'Development starter installed',
             'general': 'General starter installed',
             'skipped': 'Starter not installed (setup continued)'}


def describe(installed):
    """Human line for the setup confirmation page."""
    profile, _, _ = installed.partition(':')
    return _DESCRIBE.get(profile, 'Existing instructions kept')
