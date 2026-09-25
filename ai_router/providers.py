"""Provider adapters. Each owns model membership, request preparation, upstream target and response adaptation."""
import http.client
import json
import time
from . import (capabilities, compaction as comp, local_services, agent_handoffs,
               provider_defs, request_context, transport, turn_budget, jev_compaction)
from . import compaction_result, history_items, outbound, subscription_roster
from .capabilities import CANONICAL_ORDER
from .errors import PreparationError, SubscriptionRequired, UnknownModel
from .registry import by_slug, near_miss, upstream_id_for
from .events import log_event
from .discovered import remember
from .tool_adapter import snoop_response_identity, stream_events, ToolEvents

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


def _summary_budgets(entry):
    ceiling = getattr(entry, 'max_output_tokens', SUMMARY_OUTPUT_TOKENS)
    if (isinstance(ceiling, int) and not isinstance(ceiling, bool)
            and ceiling > SUMMARY_OUTPUT_TOKENS):
        return (SUMMARY_OUTPUT_TOKENS,
                min(SUMMARY_RETRY_OUTPUT_TOKENS, ceiling))
    return (SUMMARY_OUTPUT_TOKENS,)


def _passthrough(response):
    yield from passthrough(response)


# router.py guards compaction with this name; the external stages use the same rule.
reject_opaque_agent_items = outbound.contain


class SubscriptionProvider:
    """The client's own ChatGPT login; the router holds no credential."""

    def __init__(self):
        self.defn = provider_defs.OPENAI
        self.name = self.defn.id
        self.host = self.defn.host
        self.kind = self.defn.kind

    def owns(self, model, path, openai_models, openai_mode='subscription',
             allowed=None, *, catalogue):
        del allowed  # Subscription rows are never allowlisted.
        if openai_mode == 'none':
            return False
        if is_native_service(path):
            return True
        entry = catalogue.get(model) if isinstance(model, str) else None
        if entry is not None:
            return entry.provider == provider_defs.OPENAI.id
        return isinstance(model, str) and (model in openai_models or model in subscription_roster.HELPER_SLUGS)

    def prepare(self, model, path, payload, raw_body, headers, credentials, decoded_len=None, context=None):
        del decoded_len  # Subscription rows keep the provider's own usage.
        # The URL path token is the loopback auth; Codex >=0.153.4 omits the
        # subscription Authorization header, so forward client headers unchanged.
        fwd = {k: v for k, v in headers.items() if k.lower() not in HOP_HEADERS}
        payload, names, changed = outbound.project_subscription(payload, path)
        if changed:
            fwd = {k: v for k, v in fwd.items() if k.lower() not in ('content-encoding', 'accept-encoding')}
            fwd['Accept-Encoding'] = 'identity'
            raw_body = json.dumps(payload).encode()
        return Prepared(self.host, self.defn.path_for(provider_defs.RESPONSES, path),
                        fwd, raw_body, names, self.name, context=context)

    def adapt(self, response, tool_names, notes=None):
        if tool_names and response.status == 200:
            yield from agent_handoffs.adapt_response(response, tool_names, notes)
        elif notes is not None and response.status == 200:
            yield from snoop_response_identity(response, notes)
        else:
            yield from _passthrough(response)


class ExternalResponsesProvider:
    """One external provider serving the Codex Responses family (Plan 141)."""

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
                or is_native_service(path)):
            return False
        # Plan 068 allowlist plus the key-filtered snapshot gate
        # routing like the picker; no snapshot yet means policy decides.
        if allowed is not None and model not in allowed:
            return False
        from . import availability as _availability
        return _availability.permitted(model)

    def prepare(self, model, path, payload, raw_body, headers, credentials, decoded_len=None, context=None):
        if path not in ('/responses', '/responses/compact'):
            raise PreparationError(f'{self.defn.label} supports responses only')
        # Every model fact below reads this row: routed, the ingress snapshot (Plan 188).
        entry = context.row if context is not None else by_slug(model) if isinstance(model, str) else model
        # Before any rewrite: what this client's thread carries. The slim below
        # is invisible upstream, so provider usage alone never moves the trigger.
        carried = turn_budget.carried_tokens(payload, decoded_len) if decoded_len else None
        payload, tool_names = outbound.project_external(payload, path, model, entry)
        cap = payload['max_output_tokens']
        window = getattr(entry, 'context_window', 0) or 0
        carried = min(carried, window) if carried and window else carried
        # Context size stays the provider's call: a chars-per-token estimate
        # refused long turns the client still had room for.
        headers = dict(self.defn.request_headers)
        headers.update({'Authorization': 'Bearer ' + credentials.key_for(self.defn.id),
                        'Content-Type': 'application/json',
                        'Accept-Encoding': 'identity'})
        body = json.dumps(payload).encode()
        if len(body) > turn_budget.BODY_BUDGET:
            payload, stats = turn_budget.fit(payload, turn_budget.BODY_BUDGET, len(body))
            if stats:
                body = json.dumps(payload).encode()
                log_event('turn_trimmed', model=model, prepared_bytes=len(body), **stats)
        return Prepared(self.host, self.defn.path_for(provider_defs.RESPONSES, '/responses'),
                        headers, body, tool_names, self.name, output_cap=cap,
                        context_tokens=carried, context=context)

    def adapt(self, response, tool_names, notes=None):
        if notes is not None and not tool_names and response.status == 200:
            yield from snoop_response_identity(response, notes)
        elif tool_names and response.status == 200:
            if 'text/event-stream' in response.getheader('Content-Type', ''):
                yield from stream_events(response, tool_names, notes)
            else:
                result = json.loads(transport.read_capped(response, transport.MAX_UPSTREAM_BODY))
                if notes is not None and isinstance(result.get('model'), str):
                    notes['served_model'] = result['model']
                adapter = ToolEvents(tool_names, notes)
                result['output'] = [adapter.item(item) for item in result.get('output', [])]
                turn_budget.report_usage(result.get('usage'), notes)
                yield json.dumps(result).encode()
        else:
            yield from _passthrough(response)

    def compact(self, model, payload, key, row=None):
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
            summary = jev_compaction.summary(model, key, items, self.defn, row=row) or self.summarize(model, key, items, row)
            log_event('compact_summarized', model=model, summary_chars=len(summary))
            output = comp.build_compact_v1_output(users, summary)
            remember(items, summary)
            return output
        except ValueError as exc:
            raise PreparationError(str(exc))

    def compact_trigger(self, model, payload, key, row=None):
        """Answer a V2 trigger inline with exactly one ocx1 compaction item."""
        try:
            items = [item for item in payload.get('input', [])
                     if not (isinstance(item, dict)
                             and item.get('type') == comp.TRIGGER_TYPE)]
            users = comp.extract_user_messages(items)
            if not users:
                raise ValueError('No user messages to compact')
            summary = jev_compaction.summary(model, key, items, self.defn, row=row) or self.summarize(model, key, items, row)
            log_event('compact_triggered', model=model, summary_chars=len(summary))
            remember(items, summary)
            return [comp.v2_compaction_item(summary)]
        except ValueError as exc:
            raise PreparationError(str(exc))

    def summarize(self, model, key, payload_items, row=None):
        """`row` is the routed request's captured row; None looks up `model` live."""
        prompt = comp.COMPACT_PROMPT + '\n\nConversation:\n' + comp.transcript_for_summary(payload_items)
        levels = row.reasoning if row is not None else capabilities.REASONING_LEVELS.get(model)
        effort = min(levels, key=CANONICAL_ORDER.index) if levels else None
        entry = row if row is not None else by_slug(model) if isinstance(model, str) else None
        deadline = time.monotonic() + SUMMARY_DEADLINE_S
        budgets = _summary_budgets(entry)
        for attempt, budget in enumerate(budgets, 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log_event('compact_summary_attempt', model=model, attempt=attempt,
                          max_output_tokens=budget, outcome='deadline')
                raise TimeoutError('Compaction summarizer deadline exceeded')
            upstream = upstream_id_for(entry) if entry is not None else model
            body = {'model': upstream, 'input': [history_items.user_message_item(prompt)],
                    'max_output_tokens': budget}
            if getattr(entry, 'provider_prefs', None):
                body['provider'] = dict(entry.provider_prefs)
            if effort:
                # Never let default high effort burn the whole budget on reasoning.
                body['reasoning'] = {'effort': effort}
            conn = None
            try:
                req = json.dumps(body).encode()
                conn = http.client.HTTPSConnection(self.host,
                                                    timeout=remaining)
                headers = dict(self.defn.request_headers)
                headers.update({'Authorization': 'Bearer ' + key,
                                'Content-Type': 'application/json'})
                conn.request('POST', self.defn.path_for(
                    provider_defs.RESPONSES, '/responses'), body=req,
                    headers=headers)
                resp = conn.getresponse()
                try:
                    data = json.loads(transport.read_capped(resp, transport.MAX_UPSTREAM_BODY))
                except ValueError:
                    raise OSError('Summarizer returned invalid JSON')
                summary = compaction_result.extract_summary(resp.status, data)
            except compaction_result.IncompleteSummary:
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
             allowed=None, *, catalogue):
        del allowed, catalogue  # Native service paths are never allowlisted.
        return openai_mode == 'none' and is_native_service(path)

    def prepare(self, model, path, payload, raw_body, headers, credentials, decoded_len=None, context=None):
        del decoded_len, context  # This adapter answers locally; nothing is carried.
        local_services.answer(path)
        raise AssertionError('unreachable')

    def adapt(self, response, tool_names):
        raise AssertionError('unreachable')


def adapters(region='global'):
    """One adapter per external def serving Responses, plus the rest.

    `region` selects the endpoint profile host (Plan 145); unknown
    names fall back to the global host inside the adapter.
    """
    return (tuple(ExternalResponsesProvider(defn, region)
                  for defn in provider_defs.external_serving(provider_defs.RESPONSES))
            + (SubscriptionProvider(), LocalServicesProvider()))


def compaction_call(provider, model, path, payload, row=None):
    """Bound local serve for external compact/V2-trigger turns, else None."""
    if provider.kind != provider_defs.EXTERNAL:
        return None
    if path == '/responses/compact':
        return lambda key: provider.compact(model, payload, key, row)
    if path == '/responses' and comp.has_compaction_trigger(payload.get('input', [])):
        return lambda key: provider.compact_trigger(model, payload, key, row)
    return None


def select(model, path, openai_models=(), openai_mode='subscription',
           region='global', allowed=None, catalogue=None):
    allowset = None if allowed is None else frozenset(allowed)
    rows = request_context.capture() if catalogue is None else catalogue
    for provider in adapters(region):
        if provider.owns(model, path, openai_models, openai_mode,
                         allowed=allowset, catalogue=rows):
            return provider
    if openai_mode == 'none' and isinstance(model, str) and model in (openai_models or []):
        raise SubscriptionRequired()
    entry = rows.get(model) if isinstance(model, str) else None
    defn = provider_defs.get(entry.provider) if entry is not None else None
    if defn is not None and not defn.serves(provider_defs.RESPONSES):
        raise PreparationError(
            f'{defn.label} models are available to Claude Code only: '
            f'{entry.slug} does not serve the Codex Responses API')
    guess = near_miss(model, rows)
    if guess is not None and allowset is not None and guess not in allowset:
        guess = None  # never disclose a slug the portco policy excludes
    raise UnknownModel(model if isinstance(model, str) else None,
                       (guess,) if guess else ())
