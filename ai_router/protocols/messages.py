"""Messages protocol policy (Plan 062). Thin selector over claude.py.

Owns the Claude Code Messages ingress. Bodies stay byte-identical; retry and
model-header handling keep their existing shared behavior until a client
contract test or live gate proves a divergence.

Plan 155: the name is the constant the definition table exports, and this
family owns the Anthropic-shaped discovery listing.
"""
from .. import claude, provider_defs


class _Policy:
    name = provider_defs.MESSAGES

    def listing(self, allowed=None):
        """The discovery payload this family serves for a GET."""
        return claude.models_listing(allowed)

    def select_provider(self, model, path, state, mode):
        return claude.select(model, path, mode,
                             anthropic_mode=state.get('anthropic_mode'),
                             region=state.get('openrouter_region', 'global'),
                             allowed=state.get('allowed_models'))

    def compaction_call(self, provider, model, path, payload):
        del provider, model, path, payload
        return None


POLICY = _Policy()
