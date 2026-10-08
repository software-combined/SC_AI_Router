"""Shared external provider identity and model authorization."""
from . import availability, provider_defs


class ExternalProvider:
    def __init__(self, defn, region='global'):
        self.defn = defn
        self.name = defn.id
        self.region = region if provider_defs.valid_region(region) else 'global'
        self.host = provider_defs.region_host(defn.id, self.region) or defn.host
        self.kind = defn.kind

    def owns(self, model, path, openai_models, openai_mode='subscription',
             allowed=None, *, catalogue):
        entry = catalogue.get(model) if isinstance(model, str) else None
        if (entry is None or entry.provider != self.defn.id
                or provider_defs.native_service_path(path)):
            return False
        if allowed is not None and model not in allowed:
            return False
        return availability.permitted(model)
