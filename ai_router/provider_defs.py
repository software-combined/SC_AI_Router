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
EXTERNAL = 'external'
SUBSCRIPTION = 'subscription'


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
                 'messages_path', 'key', 'catalogue_url', 'catalogue_shape',
                 'key_info_url', 'dialect', 'native_prefixes',
                 'request_headers')

    def __init__(self, id, label, kind, host, responses_path=None,
                 messages_path=None, key=None, catalogue_url=None,
                 catalogue_shape='manual', key_info_url=None, dialect=None,
                 native_prefixes=(), request_headers=()):
        if kind not in (EXTERNAL, SUBSCRIPTION):
            raise ValueError(f'{id}: bad kind {kind!r}')
        if kind == EXTERNAL and key is None:
            raise ValueError(f'{id}: an external provider needs a key spec')
        if kind == SUBSCRIPTION and key is not None:
            raise ValueError(f'{id}: a subscription provider holds no key')
        if responses_path is None and messages_path is None:
            raise ValueError(f'{id}: serves neither responses nor messages')
        native_prefixes = tuple(native_prefixes)
        for prefix in native_prefixes:
            if not isinstance(prefix, str) or not prefix.startswith('/'):
                raise ValueError(f'{id}: bad native prefix {prefix!r}')
        self.id, self.label, self.kind, self.host = id, label, kind, host
        self.responses_path, self.messages_path = responses_path, messages_path
        self.key, self.catalogue_url = key, catalogue_url
        self.catalogue_shape, self.key_info_url = catalogue_shape, key_info_url
        self.dialect = dialect or id
        self.native_prefixes = native_prefixes
        request_headers = tuple(request_headers)
        for pair in request_headers:
            if (not isinstance(pair, tuple) or len(pair) != 2
                    or not all(isinstance(part, str) and part for part in pair)):
                raise ValueError(f'{id}: bad request header {pair!r}')
        self.request_headers = request_headers

    def serves(self, protocol):
        """True when this provider serves that protocol natively."""
        path = self.responses_path if protocol == RESPONSES else self.messages_path
        return path is not None

    def path_for(self, protocol, path):
        """Upstream path for a client path on that protocol."""
        if not self.serves(protocol):
            raise ValueError(f'{self.label} does not serve {protocol}')
        prefix = self.responses_path if protocol == RESPONSES else self.messages_path
        return (prefix or '') + path


OPENROUTER = ProviderDef(
    id='openrouter', label='OpenRouter', kind=EXTERNAL, host='openrouter.ai',
    responses_path='/api/v1', messages_path='/api',
    key=KeySpec('OPENROUTER_API_KEY', 'openrouter.key', state_key='openrouter',
                example='sk-or-v1-...'),
    catalogue_url='https://openrouter.ai/api/v1/models',
    catalogue_shape='openrouter',
    key_info_url='https://openrouter.ai/api/v1/auth/key',
    dialect='openrouter',
    request_headers=(('X-OpenRouter-Metadata', 'enabled'),))

OPENAI = ProviderDef(
    id='openai', label='OpenAI', kind=SUBSCRIPTION, host='chatgpt.com',
    responses_path='/backend-api/codex', dialect='openai',
    native_prefixes=('/alpha/', '/guardian'))

ANTHROPIC = ProviderDef(
    id='anthropic', label='Anthropic', kind=SUBSCRIPTION, host='api.anthropic.com',
    messages_path='', dialect='anthropic')


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
