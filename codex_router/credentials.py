"""Ordered OpenRouter key lookup. Read at request time so rotation needs no restart. Never log the key."""
import json
import os
from pathlib import Path

ENV_VAR = 'OPENROUTER_API_KEY'
KEY_FILE = 'openrouter.key'


def default_home():
    """Router home, resolved at call time so tests can patch the env var."""
    return Path(os.environ.get('ROUTER_HOME', Path.home() / '.codex' / 'mixed-model-router'))


class Credentials:
    def __init__(self, state, home=None, env=None):
        self.state = state
        self.home = Path(home) if home is not None else default_home()
        self.env = os.environ if env is None else env

    def openrouter_key(self):
        value = self.env.get(ENV_VAR, '').strip()
        if value:
            return value
        key_file = self.home / KEY_FILE
        if key_file.exists():
            if os.name != 'nt' and key_file.stat().st_mode & 0o077:
                raise PermissionError(f'{key_file} must be readable by the owner only (chmod 600)')
            value = key_file.read_text().strip()
            if value:
                return value
            raise LookupError(f'{key_file} is empty')
        opencode = self.state.get('opencode_auth')
        if opencode:
            try:
                auth = json.loads(Path(opencode).read_text())['openrouter']
                if auth.get('type') != 'api':
                    raise ValueError('OpenCode credential is not an API key')
                return auth['key']
            except (KeyError, TypeError, AttributeError):
                raise LookupError(f'{opencode} has no openrouter api key')
        raise LookupError(f'No OpenRouter key: set {ENV_VAR}, create {key_file}, or configure opencode_auth')

    def check(self):
        """Startup probe: raises the same errors as openrouter_key without returning the value."""
        self.openrouter_key()
        return True
