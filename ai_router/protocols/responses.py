"""Responses protocol policy (Plan 062). Thin selector over providers.py.

Owns the Codex Responses family: turns, compaction, and native service
paths. Retry and model-header handling keep their existing shared behavior;
a later client contract test or live gate owns any divergence.

Plan 155: the name is the constant the definition table exports, and the
family serves no discovery listing, so a GET row can never be routed here.
"""
from .. import provider_defs, providers


class _Policy:
    name = provider_defs.RESPONSES
    listing = None

    def select_provider(self, model, path, state, mode):
        return providers.select(
            model, path, state.get('openai_models', []), mode,
            region=state.get('openrouter_region', 'global'),
            allowed=state.get('allowed_models'))

    def compaction_call(self, provider, model, path, payload):
        return providers.compaction_call(provider, model, path, payload)


POLICY = _Policy()
