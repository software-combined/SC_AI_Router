"""Responses protocol policy (Plan 062). Thin selector over providers.py.

Owns the Codex Responses family: turns, compaction, and native service
paths. Retry and model-header handling keep their existing shared behavior;
a later client contract test or live gate owns any divergence.

Plan 155: the name is the constant the definition table exports, and the
family serves no discovery listing, so a GET row can never be routed here.
"""
from .. import provider_defs, providers, request_context


class _Policy:
    name = provider_defs.RESPONSES
    listing = None

    def resolve(self, model):
        """This request's snapshot: Responses ids are registry slugs as sent."""
        return request_context.resolve(model, request_context.capture())

    def select_provider(self, model, path, state, mode, openai_models=None,
                        catalogue=None, headers=None):
        if openai_models is None:
            openai_models = state.get('openai_models', [])
        return providers.select(
            model, path, openai_models, mode,
            region=state.get('openrouter_region', 'global'),
            allowed=state.get('allowed_models'), catalogue=catalogue)

    def compaction_call(self, provider, model, path, payload, context=None,
                        allowed=None):
        return providers.compaction_call(provider, model, path, payload,
                                         context=context, allowed=allowed)


POLICY = _Policy()
