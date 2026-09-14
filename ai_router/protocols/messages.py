"""Messages protocol policy (Plan 062). Thin selector over claude.py.

Owns the Claude Code Messages ingress. Bodies stay byte-identical; retry and
model-header handling keep their existing shared behavior until a client
contract test or live gate proves a divergence.
"""
from .. import claude


class _Policy:
    name = 'messages'

    def select_provider(self, model, path, state, mode):
        return claude.select(model, path, mode,
                             anthropic_mode=state.get('anthropic_mode'),
                             region=state.get('openrouter_region', 'global'),
                             allowed=state.get('allowed_models'))

    def compaction_call(self, provider, model, path, payload):
        del provider, model, path, payload
        return None


POLICY = _Policy()
