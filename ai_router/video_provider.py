"""Video job submission through Codex's Responses entry point."""
from . import media, registry, transport
from .errors import PreparationError
from .external_provider import ExternalProvider


class VideoResponsesProvider(ExternalProvider):
    def owns(self, model, path, openai_models, openai_mode='subscription',
             allowed=None, *, catalogue):
        row = catalogue.get(model) if isinstance(model, str) else None
        return (getattr(row, 'media_kind', None) == 'video' and path == '/responses'
                and super().owns(model, path, openai_models, openai_mode,
                                 allowed, catalogue=catalogue))

    def prepare(self, model, path, payload, raw_body, headers, credentials,
                decoded_len=None, context=None):
        row = context.row if context is not None else registry.by_slug(model)
        kind, tool = media.media_tool(payload)
        if (path != '/responses' or getattr(row, 'media_kind', None) != 'video'
                or (kind is not None and kind != 'video')):
            raise PreparationError('Media model and generation request do not match')
        return media.prepared(self, 'video', tool or {}, model, row, payload,
                              registry.upstream_id_for(row), credentials, context)

    def adapt(self, response, tool_names, notes=None):
        yield from transport.passthrough(response)

    def repair_rejected(self, prepared, described, raw):
        return None  # A video refusal is never a chat-schema repair candidate.
