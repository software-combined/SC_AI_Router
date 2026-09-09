"""Responses protocol policy (Plan 062). Thin selector over providers.py.

Owns the Codex Responses family: turns, compaction, and native service
paths. Retry and model-header handling keep their existing shared behavior;
a later client contract test or live gate owns any divergence.
"""
from .. import providers


class _Policy:
    name = 'responses'

    def select_provider(self, model, path, state, mode):
        return providers.select(
            model, path, state.get('openai_models', []), mode)

    def compaction_call(self, provider, model, path, payload):
        return providers.compaction_call(provider, model, path, payload)


POLICY = _Policy()
