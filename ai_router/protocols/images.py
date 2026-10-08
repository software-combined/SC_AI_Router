"""Standalone Images follow their originating chat's provider connection."""
from .. import codex_route, image_provider, media_origin, provider_defs, providers, request_context
from ..errors import PreparationError, UnknownModel


class _Policy:
    name = provider_defs.IMAGES
    listing = None

    def resolve(self, model):
        return request_context.resolve(model, request_context.capture())

    def origin_route(self, model, path, state, mode, payload, headers, turns, context):
        turn = media_origin.header(headers, 'x-codex-image-turn-id')
        chat = payload.get('chat_model')
        if turn is None and chat is None:
            # Standalone API callers retain their explicit install/profile contract.
            return context, self.select_provider(model, path, state, mode,
                catalogue=context.catalogue, headers=headers)
        origin = turns.lookup(turn) if turn is not None else None
        if origin is not None:
            if chat is not None and chat != origin.context.slug:
                raise PreparationError('Image chat_model conflicts with its originating turn')
            chat, rows = origin.context.slug, origin.context.catalogue
        else:
            rows = context.catalogue
        if origin is not None and origin.provider == provider_defs.OPENAI.id:
            if mode == 'none':
                raise PreparationError('The originating chat connection is no longer available')
            # Admission already resolved native membership, including recovered chats.
            owner = providers.SubscriptionProvider()
        else:
            owner = chat_provider(chat, state, mode, rows)
        if origin is not None and owner.name != origin.provider:
            raise PreparationError('The originating chat connection is no longer available')
        context = request_context.resolve(model, rows)
        if owner.kind == provider_defs.SUBSCRIPTION:
            if codex_route.switched(headers) or not isinstance(model, str) or model not in image_provider.NATIVE_MODELS:
                raise PreparationError('Use a native image model for this OpenAI chat connection')
            return context, image_provider.SubscriptionImagesProvider()
        row = image_provider.row_for(model, rows)
        if row is None or row.provider != owner.name:
            raise PreparationError('Choose an image model on the originating chat provider')
        return context, image_provider.ExternalImagesProvider(row,
            state.get('openrouter_region', 'global'), state.get('allowed_models'))

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


def chat_provider(model, state, mode, rows):
    row = rows.get(model) if isinstance(model, str) else None
    if getattr(row, 'media_kind', None):
        raise PreparationError('chat_model must be a conversation model, not a media model')
    return providers.select(model, '/responses', state.get('openai_models', []), mode,
        region=state.get('openrouter_region', 'global'), allowed=state.get('allowed_models'), catalogue=rows)
