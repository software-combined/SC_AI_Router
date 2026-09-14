"""Provider adapters. Each owns model membership, request preparation, upstream target and response adaptation."""
import http.client
import json
import time
from . import capabilities, compaction as comp, local_services, agent_handoffs, provider_defs
from .standalone_outputs import materialize_outputs
from . import subscription_history, context_recovery
from .capabilities import CANONICAL_ORDER, check_effort, check_images, input_modalities
from .image_items import note_images, strip_images
from .errors import PreparationError, SubscriptionRequired, UnknownModel
from .registry import by_slug, near_miss
from .runtime import log_event
from .discovered import remember
from .tool_adapter import prepare_tools, snoop_response_identity, stream_events, ToolEvents

# Transport leaves live in transport.py (Plan 062); these aliases keep
# existing importers working until the protocol split completes.
from .transport import HOP_HEADERS, Prepared, passthrough
NATIVE_SERVICE_PATHS = {'/alpha/search', '/alpha/notes/v2/thread_hint', '/guardian', '/guardian-classifier'}


def is_native_service(path):
    # Any native path the subscription definitions claim (prefix rule).
    return provider_defs.native_service_path(path)
SUMMARY_OUTPUT_TOKENS = 4000
SUMMARY_RETRY_OUTPUT_TOKENS = 8000
SUMMARY_DEADLINE_S = 120


def _summary_budgets(model):
    entry = by_slug(model) if isinstance(model, str) else None
    ceiling = getattr(entry, 'max_output_tokens', SUMMARY_OUTPUT_TOKENS)
    if (isinstance(ceiling, int) and not isinstance(ceiling, bool)
            and ceiling > SUMMARY_OUTPUT_TOKENS):
        return (SUMMARY_OUTPUT_TOKENS,
                min(SUMMARY_RETRY_OUTPUT_TOKENS, ceiling))
    return (SUMMARY_OUTPUT_TOKENS,)


def _passthrough(response):
    yield from passthrough(response)


def reject_opaque_agent_items(items):
    """Fail closed on unreadable encrypted briefs before any dispatch."""
    if comp.has_opaque_agent_item(items):
        raise PreparationError(
            'unsupported encrypted agent instructions; '
            'resend the assignment as plain text')


class SubscriptionProvider:
    """The client's own ChatGPT login; the router holds no credential."""

    def __init__(self):
        self.defn = provider_defs.OPENAI
        self.name = self.defn.id
        self.host = self.defn.host
        self.kind = self.defn.kind

    def owns(self, model, path, openai_models, openai_mode='subscription',
             allowed=None):
        del allowed  # Subscription rows are never allowlisted.
        if openai_mode == 'none':
            return False
        if is_native_service(path):
            return True
        entry = by_slug(model) if isinstance(model, str) else None
        if entry is not None:
            return entry.provider == provider_defs.OPENAI.id
        return isinstance(model, str) and model in openai_models

    def prepare(self, model, path, payload, raw_body, headers, credentials):
        # The URL path token is the loopback auth; Codex >=0.153.4 omits the
        # subscription Authorization header, so forward client headers unchanged.
        fwd = {k: v for k, v in headers.items() if k.lower() not in HOP_HEADERS}
        normalized = (subscription_history.normalize(payload)
                      if path in ('/responses', '/responses/compact') else payload)
        if path == '/responses':
            normalized = context_recovery.normalize(normalized)
        history_changed = normalized is not payload
        payload = normalized
        try:
            names = agent_handoffs.add_plaintext_tools(payload) if path == '/responses' else set()
        except ValueError as exc:
            raise PreparationError(str(exc)) from exc
        if names or history_changed:
            fwd = {k: v for k, v in fwd.items() if k.lower() not in ('content-encoding', 'accept-encoding')}
            fwd['Accept-Encoding'] = 'identity'
            raw_body = json.dumps(payload).encode()
        return Prepared(self.host, self.defn.path_for(provider_defs.RESPONSES, path),
                        fwd, raw_body, names, self.name)

    def adapt(self, response, tool_names, notes=None):
        if tool_names and response.status == 200:
            yield from agent_handoffs.adapt_response(response, tool_names, notes)
        elif notes is not None and response.status == 200:
            yield from snoop_response_identity(response, notes)
        else:
            yield from _passthrough(response)


class ExternalResponsesProvider:
    """One external provider serving the Codex Responses family (Plan 141)."""

    def __init__(self, defn):
        self.defn = defn
        self.name = defn.id
        self.host = defn.host
        self.kind = defn.kind

    def owns(self, model, path, openai_models, openai_mode='subscription',
             allowed=None):
        entry = by_slug(model) if isinstance(model, str) else None
        if (entry is None or entry.provider != self.defn.id
                or is_native_service(path)):
            return False
        # Plan 068: a portco allowlist gates routing, never just the picker.
        # None means no policy provisioned (today's behavior); subscription
        # rows are unaffected by any list.
        return allowed is None or model in allowed

    def prepare(self, model, path, payload, raw_body, headers, credentials):
        if path not in ('/responses', '/responses/compact'):
            raise PreparationError(f'{self.defn.label} supports responses only')
        # Contain before anything else: an opaque brief must never reach
        # credential lookup or upstream dispatch, where a child would infer
        # its assignment from inherited context instead.
        reject_opaque_agent_items(payload.get('input', []))
        if path == '/responses':
            payload = context_recovery.normalize(payload)
        # Standalone outputs (no call_id) are delegated messages, not orphans.
        payload['input'] = materialize_outputs(payload.get('input', []))
        # Scrub before prepare_tools: fragments KeyError its indexing, and
        # tool_search_output items (released-tool discovery) are never scrubbed.
        payload['input'] = comp.scrub_tool_fragments(payload.get('input', []))
        try:
            aliases = agent_handoffs.add_plaintext_tools(payload)
            tool_names = prepare_tools(payload)
            tool_names.handoffs = aliases
            rewritten = comp.strip_reasoning_blobs(comp.rewrite_input(payload.get('input', [])))
        except ValueError as exc:
            raise PreparationError(str(exc))
        try:
            check_images(model, rewritten)
        except ValueError as exc:
            raise PreparationError(str(exc))
        keep_images = 'image' in input_modalities(model) if isinstance(model, str) else True
        entry = by_slug(model) if isinstance(model, str) else model
        payload['input'] = note_images(rewritten) if getattr(entry, 'drop_images', False) else strip_images(rewritten, keep_images)
        reasoning = payload.get('reasoning')
        try:
            check_effort(model,
                         reasoning.get('effort') if isinstance(reasoning, dict) else None)
        except ValueError as exc:
            raise PreparationError(str(exc))
        payload.pop('service_tier', None)
        if entry is None:
            # Defence in depth: select()/owns() already refuses a slug that is
            # not a matching registry row, so this only fires for a direct
            # prepare() call and never for a routed request.
            raise PreparationError(f'unknown model: {model}')
        limit = entry.max_output_tokens
        window = getattr(entry, 'context_window', 0) or 0
        if window:  # reservation counts against context; keep half for input
            limit = min(limit, window // 2)
        # Codex omits the cap and compacts at 90% of context. Its remaining
        # headroom must fit our default output, not the provider's maximum.
        default = min(32000, entry.max_output_tokens)
        if window:
            default = min(default, window - window * 9 // 10)
        requested = payload.get('max_output_tokens')
        payload['max_output_tokens'] = min(requested, limit) if requested else default
        # Context size stays the provider's call: a chars-per-token estimate
        # refused long turns the client still had room for.
        headers = dict(self.defn.request_headers)
        headers.update({'Authorization': 'Bearer ' + credentials.key_for(self.defn.id),
                        'Content-Type': 'application/json',
                        'Accept-Encoding': 'identity'})
        return Prepared(self.host, self.defn.path_for(provider_defs.RESPONSES, '/responses'),
                        headers,
                        json.dumps(payload).encode(), tool_names, self.name)

    def adapt(self, response, tool_names, notes=None):
        if notes is not None and not tool_names and response.status == 200:
            yield from snoop_response_identity(response, notes)
        elif tool_names and response.status == 200:
            if 'text/event-stream' in response.getheader('Content-Type', ''):
                yield from stream_events(response, tool_names, notes)
            else:
                result = json.load(response)
                if notes is not None and isinstance(result.get('model'), str):
                    notes['served_model'] = result['model']
                adapter = ToolEvents(tool_names, notes)
                result['output'] = [adapter.item(item) for item in result.get('output', [])]
                yield json.dumps(result).encode()
        else:
            yield from _passthrough(response)

    def compact(self, model, payload, key):
        try:
            items = payload.get('input', [])
            kinds, shapes = {}, {}
            for _item in items if isinstance(items, list) else []:
                kind = _item.get('type') if isinstance(_item, dict) else '?'
                kinds[kind] = kinds.get(kind, 0) + 1
                if isinstance(_item, dict):
                    shapes.setdefault(kind, set()).update(_item.keys())
            log_event('compact_started', model=model,
                      input_items=len(items) if isinstance(items, list) else -1,
                      item_kinds=kinds,
                      item_keys={k: sorted(v) for k, v in shapes.items()})
            users = comp.extract_user_messages(items)
            if not users:
                raise ValueError('No user messages to compact')
            summary = self.summarize(model, key, items)
            log_event('compact_summarized', model=model, summary_chars=len(summary))
            output = comp.build_compact_v1_output(users, summary)
            remember(items, summary)
            return output
        except ValueError as exc:
            raise PreparationError(str(exc))

    def compact_trigger(self, model, payload, key):
        """Answer a V2 trigger inline with exactly one ocx1 compaction item."""
        try:
            items = [item for item in payload.get('input', [])
                     if not (isinstance(item, dict)
                             and item.get('type') == comp.TRIGGER_TYPE)]
            users = comp.extract_user_messages(items)
            if not users:
                raise ValueError('No user messages to compact')
            summary = self.summarize(model, key, items)
            log_event('compact_triggered', model=model, summary_chars=len(summary))
            remember(items, summary)
            return [comp.v2_compaction_item(summary)]
        except ValueError as exc:
            raise PreparationError(str(exc))

    def summarize(self, model, key, payload_items):
        transcript = comp.transcript_for_summary(payload_items)
        prompt = comp.COMPACT_PROMPT + '\n\nConversation:\n' + transcript
        levels = capabilities.REASONING_LEVELS.get(model)
        effort = min(levels, key=CANONICAL_ORDER.index) if levels else None
        deadline = time.monotonic() + SUMMARY_DEADLINE_S
        budgets = _summary_budgets(model)
        for attempt, budget in enumerate(budgets, 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log_event('compact_summary_attempt', model=model, attempt=attempt,
                          max_output_tokens=budget, outcome='deadline')
                raise TimeoutError('Compaction summarizer deadline exceeded')
            body = {'model': model, 'input': [comp.user_message_item(prompt)],
                    'max_output_tokens': budget}
            if effort:
                # Never let default high effort burn the whole budget on reasoning.
                body['reasoning'] = {'effort': effort}
            conn = None
            try:
                req = json.dumps(body).encode()
                conn = http.client.HTTPSConnection(self.defn.host,
                                                    timeout=remaining)
                headers = dict(self.defn.request_headers)
                headers.update({'Authorization': 'Bearer ' + key,
                                'Content-Type': 'application/json'})
                conn.request('POST', self.defn.path_for(
                    provider_defs.RESPONSES, '/responses'), body=req,
                    headers=headers)
                resp = conn.getresponse()
                try:
                    data = json.load(resp)
                except ValueError:
                    raise OSError('Summarizer returned invalid JSON')
                summary = comp.extract_summary(resp.status, data)
            except comp.IncompleteSummary:
                if attempt == len(budgets):
                    log_event('compact_summary_attempt', model=model,
                              attempt=attempt, max_output_tokens=budget,
                              outcome='rejected')
                    raise
                if time.monotonic() >= deadline:
                    log_event('compact_summary_attempt', model=model,
                              attempt=attempt, max_output_tokens=budget,
                              outcome='deadline')
                    raise TimeoutError('Compaction summarizer deadline exceeded')
                log_event('compact_summary_attempt', model=model,
                          attempt=attempt, max_output_tokens=budget,
                          outcome='retry')
                continue
            except Exception:
                log_event('compact_summary_attempt', model=model, attempt=attempt,
                          max_output_tokens=budget, outcome='failed')
                raise
            else:
                log_event('compact_summary_attempt', model=model, attempt=attempt,
                          max_output_tokens=budget, outcome='completed')
                return summary
            finally:
                if conn is not None:
                    conn.close()


class LocalServicesProvider:
    name = 'local-services'
    host = None
    kind = 'local'
    defn = None

    def owns(self, model, path, openai_models, openai_mode='subscription',
             allowed=None):
        del allowed  # Native service paths are never allowlisted.
        return openai_mode == 'none' and is_native_service(path)

    def prepare(self, model, path, payload, raw_body, headers, credentials):
        local_services.answer(path)
        raise AssertionError('unreachable')

    def adapt(self, response, tool_names):
        raise AssertionError('unreachable')


def adapters():
    """One adapter per external def serving Responses, plus the rest.

    Built per call from the definition table, so a provider added to that
    table is routable without a second registration step (Plan 141).
    """
    return (tuple(ExternalResponsesProvider(defn)
                  for defn in provider_defs.external_serving(provider_defs.RESPONSES))
            + (SubscriptionProvider(), LocalServicesProvider()))


def compaction_call(provider, model, path, payload):
    """Bound local serve for external compact/V2-trigger turns, else None."""
    if provider.kind != provider_defs.EXTERNAL:
        return None
    if path == '/responses/compact':
        return lambda key: provider.compact(model, payload, key)
    if (path == '/responses'
            and comp.has_compaction_trigger(payload.get('input', []))):
        return lambda key: provider.compact_trigger(model, payload, key)
    return None


def select(model, path, openai_models=(), openai_mode='subscription',
           allowed=None):
    allowset = None if allowed is None else frozenset(allowed)
    for provider in adapters():
        if provider.owns(model, path, openai_models, openai_mode,
                         allowed=allowset):
            return provider
    if openai_mode == 'none' and isinstance(model, str) and model in (openai_models or []):
        raise SubscriptionRequired()
    entry = by_slug(model) if isinstance(model, str) else None
    defn = provider_defs.get(entry.provider) if entry is not None else None
    if defn is not None and not defn.serves(provider_defs.RESPONSES):
        raise PreparationError(
            f'{defn.label} models are available to Claude Code only: '
            f'{entry.slug} does not serve the Codex Responses API')
    guess = near_miss(model)
    if guess is not None and allowset is not None and guess not in allowset:
        guess = None  # never disclose a slug the portco policy excludes
    raise UnknownModel(model if isinstance(model, str) else None,
                       (guess,) if guess else ())
