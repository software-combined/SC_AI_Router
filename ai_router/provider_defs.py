"""One definition per upstream provider (Plan 141).

Every upstream fact lives here and nowhere else: host, endpoint prefixes,
where a key resolves from, the live model catalogue, the key-info endpoint,
and the failure/native-path dialect. The boundary test enforces that no
built-in provider host, key name or catalogue URL appears elsewhere under
`ai_router/`, so adding or swapping a provider is one entry here plus
registry rows.

Pure leaf: stdlib only, no I/O, no `ai_router` imports, and parseable as
Python 3.9 because `packaging/` spec-loads it on the installer surface.

`kind` is `external` (billed on the provider's own key) or `subscription`
(the client's own login). `dialect` names the upstream failure envelope and
also which backend's native helper paths a provider owns: `openai` is the
ChatGPT backend, `anthropic` is the Anthropic Messages API, and
`openrouter` is an OpenAI-compatible Responses upstream whose errors arrive
in OpenRouter's metadata envelope.
"""

RESPONSES = 'responses'
MESSAGES = 'messages'
IMAGES = 'images'
VIDEOS = 'videos'
EXTERNAL = 'external'
SUBSCRIPTION = 'subscription'

DIALECT_OPENROUTER = 'openrouter'
DIALECT_OPENAI = 'openai'
DIALECT_ANTHROPIC = 'anthropic'
DIALECT_OPENAI_COMPATIBLE = 'openai_compatible'
# Dialects billed on the provider's own key. They share the deterministic
# refusal cache, the context-error frame and the key window a 401 opens.
# The subscription dialects answer with the client's own login instead.
EXTERNAL_DIALECTS = (DIALECT_OPENROUTER, DIALECT_OPENAI_COMPATIBLE)
DIALECTS = EXTERNAL_DIALECTS + (DIALECT_OPENAI, DIALECT_ANTHROPIC)
# Key-info body shapes a provider may declare: OpenRouter's {"data": {...}}
# envelope, any 2xx meaning a live key, or no endpoint at all.
KEY_INFO_SHAPES = ('openrouter', 'plain', 'none')


class KeySpec:
    """Where one provider's API key resolves from, in precedence order.

    `state_key` is the entry name inside the OpenCode auth file, used only
    when neither the env var nor the key file supplies a key.
    """

    __slots__ = ('env', 'file', 'state_key', 'example')

    def __init__(self, env, file, state_key=None, example=''):
        self.env = env
        self.file = file
        self.state_key = state_key
        self.example = example


class ProviderDef:
    """One upstream: transport target, credential, catalogue and dialect.

    A `None` path means this provider does not serve that protocol; an empty
    string is a real prefix (the Anthropic API takes the client path as-is).
    """

    __slots__ = ('id', 'label', 'kind', 'host', 'responses_path',
                 'messages_path', 'images_path', 'videos_path',
                 'key', 'catalogue_url', 'catalogue_shape',
                 'key_info_url', 'key_info_shape', 'dialect', 'native_prefixes',
                 'request_headers', 'subscription_label', 'decisions_path',
                 'decisions_model')

    def __init__(self, id, label, kind, host, responses_path=None,
                 messages_path=None, images_path=None, videos_path=None,
                 key=None, catalogue_url=None,
                 catalogue_shape='manual', key_info_url=None,
                 key_info_shape='openrouter', dialect=None,
                 subscription_label=None,
                 decisions_path=None, decisions_model=None,
                 native_prefixes=(), request_headers=()):
        if kind not in (EXTERNAL, SUBSCRIPTION):
            raise ValueError(f'{id}: bad kind {kind!r}')
        dialect = dialect or id
        if dialect not in DIALECTS:
            raise ValueError(f'{id}: bad dialect {dialect!r}')
        if key_info_shape not in KEY_INFO_SHAPES:
            raise ValueError(f'{id}: bad key info shape {key_info_shape!r}')
        if kind == EXTERNAL and key is None:
            raise ValueError(f'{id}: an external provider needs a key spec')
        if kind == SUBSCRIPTION and key is not None:
            raise ValueError(f'{id}: a subscription provider holds no key')
        paths = (responses_path, messages_path, images_path, videos_path)
        if all(path is None for path in paths):
            raise ValueError(f'{id}: serves no protocol')
        native_prefixes = tuple(native_prefixes)
        for prefix in native_prefixes:
            if not isinstance(prefix, str) or not prefix.startswith('/'):
                raise ValueError(f'{id}: bad native prefix {prefix!r}')
        self.id, self.label, self.kind, self.host = id, label, kind, host
        self.responses_path, self.messages_path = responses_path, messages_path
        self.images_path, self.videos_path = images_path, videos_path
        self.key, self.catalogue_url = key, catalogue_url
        self.catalogue_shape, self.key_info_url = catalogue_shape, key_info_url
        self.key_info_shape, self.dialect = key_info_shape, dialect
        # An external route serves no login, so its refusals keep neutral text.
        self.subscription_label = None
        if kind == SUBSCRIPTION:
            self.subscription_label = subscription_label or f'{label} subscription'
        self.native_prefixes = native_prefixes
        request_headers = tuple(request_headers)
        for pair in request_headers:
            if (not isinstance(pair, tuple) or len(pair) != 2
                    or not all(isinstance(part, str) and part for part in pair)):
                raise ValueError(f'{id}: bad request header {pair!r}')
        self.request_headers = request_headers
        # A typed-decision endpoint is not a chat route: None means none.
        self.decisions_path = decisions_path
        self.decisions_model = decisions_model

    def serves(self, protocol):
        """True when this provider serves that protocol natively."""
        return self._prefix(protocol) is not None

    def _prefix(self, protocol):
        return {RESPONSES: self.responses_path, MESSAGES: self.messages_path,
                IMAGES: self.images_path, VIDEOS: self.videos_path}.get(protocol)

    def path_for(self, protocol, path):
        """Upstream path for a client path on that protocol."""
        if not self.serves(protocol):
            raise ValueError(f'{self.label} does not serve {protocol}')
        return (self._prefix(protocol) or '') + path

    def sends_context_error_frame(self):
        """True when this upstream's error body can name a context overrun."""
        return self.dialect in EXTERNAL_DIALECTS

    def opens_key_window_on_auth_failure(self):
        """True when a rejected key should offer this provider's key window."""
        return self.dialect in EXTERNAL_DIALECTS

    def caches_deterministic_refusals(self):
        """True when this upstream repeats itself, so a refusal can be cached."""
        return self.dialect in EXTERNAL_DIALECTS


OPENROUTER = ProviderDef(
    id='openrouter', label='OpenRouter', kind=EXTERNAL, host='openrouter.ai',
    responses_path='/api/v1', messages_path='/api',
    images_path='/api/v1/images', videos_path='/api/v1/videos',
    key=KeySpec('OPENROUTER_API_KEY', 'openrouter.key', state_key='openrouter',
                example='sk-or-v1-...'),
    catalogue_url='https://openrouter.ai/api/v1/models',
    catalogue_shape='openrouter',
    key_info_url='https://openrouter.ai/api/v1/auth/key',
    dialect=DIALECT_OPENROUTER,
    decisions_path='/api/alpha/decisions',
    decisions_model='typesafe/jev-1.13-20260917',
    request_headers=(('X-OpenRouter-Metadata', 'enabled'),))

# Regional endpoint profiles for one external provider. A profile names the
# host that serves inference and key-filtered discovery for an enforced
# data region; `global` is today's host. Profiles carry hosts only, never
# credentials or policy: the workspace allowed_data_regions decides which
# profile a machine uses, and requests never fall back outside it.
OPENROUTER_REGIONS = {
    'global': 'openrouter.ai',
    'us': 'us.openrouter.ai',
    'eu': 'eu.openrouter.ai',
}
OPENROUTER_REGION_PATH = 'openrouter-region'


def region_host(provider_id, region='global'):
    # Inference host for one provider and region profile. Unknown
    # providers and unknown regions fail closed to None so the caller
    # refuses rather than guessing a host outside the region.
    if provider_id != OPENROUTER.id:
        return None
    if not isinstance(region, str):
        region = 'global'
    return OPENROUTER_REGIONS.get(region)


def valid_region(region):
    # True for a known OpenRouter region profile name.
    return isinstance(region, str) and region in OPENROUTER_REGIONS

OPENAI = ProviderDef(
    id='openai', label='OpenAI', kind=SUBSCRIPTION, host='chatgpt.com',
    images_path='/backend-api/codex/images',
    responses_path='/backend-api/codex', catalogue_url='https://chatgpt.com/backend-api/codex/models',
    catalogue_shape='codex', dialect=DIALECT_OPENAI,
    key_info_shape='none', subscription_label='ChatGPT subscription',
    native_prefixes=('/alpha/', '/guardian'))

ANTHROPIC = ProviderDef(
    id='anthropic', label='Anthropic', kind=SUBSCRIPTION, host='api.anthropic.com',
    messages_path='', dialect=DIALECT_ANTHROPIC, key_info_shape='none',
    subscription_label='Claude subscription')


PROVIDERS = (OPENROUTER, OPENAI, ANTHROPIC)
BY_ID = {provider.id: provider for provider in PROVIDERS}
DEFAULT_EXTERNAL = OPENROUTER.id


def get(provider_id):
    """ProviderDef for an id, or None when the id is unknown."""
    return BY_ID.get(provider_id) if isinstance(provider_id, str) else None


def is_external(provider_id):
    provider = get(provider_id)
    return provider is not None and provider.kind == EXTERNAL


def label_for(provider_id):
    """Human label for an id; the id itself when unknown."""
    provider = get(provider_id)
    return provider.label if provider is not None else str(provider_id)


def external_defs():
    return tuple(p for p in PROVIDERS if p.kind == EXTERNAL)


def subscription_ids():
    return tuple(p.id for p in PROVIDERS if p.kind == SUBSCRIPTION)


def native_service_path(path):
    """True when a subscription definition claims this path as a native service.

    The path is forwarded verbatim with the client's own login, so a dot
    segment, a percent-encoded dot or a backslash is refused before the
    prefix test: `/alpha/../v1/x` must never reach the upstream.
    """
    if not isinstance(path, str) or '\\' in path or '%2e' in path.lower():
        return False
    if any(segment in ('.', '..') for segment in path.split('/')):
        return False
    return any(path.startswith(prefix)
               for provider in PROVIDERS if provider.kind == SUBSCRIPTION
               for prefix in provider.native_prefixes)


def external_serving(protocol):
    """External defs serving one protocol, in declaration order."""
    return tuple(p for p in external_defs() if p.serves(protocol))


def external_catalogues(shape=None):
    """External defs with a live model catalogue, optionally of one shape."""
    return tuple(p for p in external_defs()
                 if p.catalogue_url and (shape is None or p.catalogue_shape == shape))
