"""Shared external provider identity and model authorization."""
from . import availability, provider_defs, registry


class ExternalProvider:
    """One external provider; `region` is that provider's region value.

    OpenRouter's region is a named profile; a regional provider's is an
    AWS region. The definition table builds the host and fails closed, so
    an adapter with no host refuses rather than guessing an endpoint.
    """

    def __init__(self, defn, region='global'):
        self.defn = defn
        self.name = defn.id
        if defn.regional:
            self.region = region if provider_defs.valid_bedrock_region(region) else 'us-east-1'
        else:
            self.region = region if provider_defs.valid_region(region) else 'global'
        self.host = provider_defs.host_for(defn.id, self.region)
        self.kind = defn.kind

    def owns(self, model, path, openai_models, openai_mode='subscription',
             allowed=None, *, catalogue):
        entry = catalogue.get(model) if isinstance(model, str) else None
        if (entry is None or entry.provider != self.defn.id
                or provider_defs.native_service_path(path)):
            return False
        if not registry.row_serves(entry, provider_defs.RESPONSES):
            return False
        if allowed is not None and model not in allowed:
            return False
        return availability.permitted(model, provider_id=self.defn.id)
