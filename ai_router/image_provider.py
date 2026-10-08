"""Adapters for Codex's standalone Images wire format."""
from . import availability, media, provider_defs, request_context, transport
from .errors import PreparationError, UnknownModel
from .providers import SubscriptionProvider

IMAGE_POST_PATHS = frozenset(('/images/generations', '/images/edits'))


def row_for(model, catalogue):
    row = catalogue.get(model)
    if row is not None and row.media_kind == 'image':
        return row
    matches = [row for row in catalogue.values() if row.media_kind == 'image'
               and (row.upstream_id or row.slug).rsplit('/', 1)[-1] == model]
    return matches[0] if len(matches) == 1 else None


class SubscriptionImagesProvider(SubscriptionProvider):
    def prepare(self, model, path, payload, raw_body, headers, credentials,
                decoded_len=None, context=None):
        forwarded = {key: value for key, value in headers.items()
                     if key.lower() not in transport.HOP_HEADERS}
        return transport.Prepared(self.host,
            self.defn.path_for(provider_defs.IMAGES, path[len('/images'):]),
            forwarded, raw_body, {}, self.name, context=context,
            decoded_body_bytes=decoded_len)


class ExternalImagesProvider:
    def __init__(self, row, region='global', allowed=None):
        self.row, self.allowed = row, allowed
        self.defn = provider_defs.get(row.provider)
        self.name, self.kind = self.defn.id, self.defn.kind
        self.host = provider_defs.region_host(self.name, region) or self.defn.host

    def prepare(self, model, path, payload, raw_body, headers, credentials,
                decoded_len=None, context=None):
        if path != '/images/generations':
            raise PreparationError('External image editing is not available yet')
        if (self.allowed is not None and self.row.slug not in self.allowed
                or not availability.permitted(self.row.slug)):
            raise UnknownModel(model)
        context = request_context.retarget(context, self.row.slug)
        prompt = payload.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip():
            raise PreparationError('Image generation needs a text prompt')
        options = dict(payload)
        if options.get('size') == 'auto':
            options.pop('size')
        turn = {'input': [{'role': 'user', 'content': prompt}]}
        prepared = media.prepared(self, 'image', options, model, self.row, turn,
                                  self.row.upstream_id or self.row.slug,
                                  credentials, context)
        prepared.response_adapter = media.native_image_response
        return prepared

    def adapt(self, response, tool_names, notes=None):
        yield from transport.passthrough(response)

    def repair_rejected(self, prepared, described, raw):
        return None
