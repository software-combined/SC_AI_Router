"""Standalone Images dispatch, preserving the install's billing mode."""
from .. import codex_route, image_provider, provider_defs, request_context
from ..errors import UnknownModel


class _Policy:
    name = provider_defs.IMAGES
    listing = None

    def resolve(self, model):
        return request_context.resolve(model, request_context.capture())

    def select_provider(self, model, path, state, mode, openai_models=None,
                        catalogue=None, headers=None):
        row = image_provider.row_for(model, catalogue)
        if mode != 'none' and model not in catalogue and not codex_route.switched(headers or {}):
            return image_provider.SubscriptionImagesProvider()
        if row is None:
            raise UnknownModel(model)
        return image_provider.ExternalImagesProvider(row,
            state.get('openrouter_region', 'global'), state.get('allowed_models'))

    def compaction_call(self, provider, model, path, payload, context=None,
                        allowed=None):
        return None


POLICY = _Policy()
