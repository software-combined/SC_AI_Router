"""Messages protocol policy (Plan 062). Thin selector over claude.py.

Owns Claude Code Messages ingress. Native bodies stay byte-identical;
external compatibility, outcome rendering and bounded stream recovery use
the shared projection and attempt owners.

Plan 155: the name is the constant the definition table exports, and this
family owns the Anthropic-shaped discovery listing.
"""
from .. import claude, provider_defs, request_context


class _Policy:
    name = provider_defs.MESSAGES

    def listing(self, allowed=None):
        """The discovery payload this family serves for a GET."""
        return claude.models_listing(allowed)

    def resolve(self, model):
        """This request's snapshot, with a discovery alias already unaliased."""
        catalogue = request_context.capture()
        return request_context.resolve(model, catalogue, claude.resolve(model, catalogue))

    def select_provider(self, model, path, state, mode, openai_models=None,
                        catalogue=None, headers=None):
        del openai_models
        return claude.select(model, path, mode,
                             anthropic_mode=state.get('anthropic_mode'),
                             region=state.get('openrouter_region', 'global'),
                             allowed=state.get('allowed_models'), catalogue=catalogue)

    def compaction_call(self, provider, model, path, payload, context=None,
                        allowed=None):
        del provider, model, path, payload, context, allowed
        return None


POLICY = _Policy()
