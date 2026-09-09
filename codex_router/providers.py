"""Provider adapters. Each owns model membership, request preparation, upstream target and response adaptation."""
import http.client
import json
import re
from . import compaction as comp, local_services, agent_handoffs
from .capabilities import (CANONICAL_ORDER, OPENROUTER_HOST, REASONING_LEVELS, check_effort,
                              check_images, input_modalities)
from .errors import ContextWindowExceeded, PreparationError
from .registry import by_slug
from .runtime import log_event
from .discovered import remember
from .tool_adapter import prepare_tools, snoop_response_identity, stream_events, ToolEvents

# Transport leaves live in transport.py (Plan 062); these aliases keep
# existing importers working until the protocol split completes.
from .transport import HOP_HEADERS, Prepared, passthrough, relay_headers
NATIVE_SERVICE_PATHS = {'/alpha/search', '/alpha/notes/v2/thread_hint', '/guardian', '/guardian-classifier'}


def is_context_error(body):
    """Recognize explicit upstream codes, never infer from user-bearing prose."""
    try:
        error = json.loads(body)['error']
        if error.get('code') == 'context_length_exceeded':
            return True
        raw = error.get('metadata', {}).get('raw')
        return (isinstance(raw, str)
                and json.loads(raw)['error'].get('code') == 'context_length_exceeded')
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def upstream_retry_after(response, prepared, metrics):
    """Consume an upstream 429 and return its Retry-After; None otherwise.

    Codex treats a bare 429 as turn-fatal, so the caller must answer 503.
    """
    if response.status != 429:
        return None
    response.read()
    log_event('upstream_rate_limited', provider=prepared.provider, path=metrics['path'])
    return response.getheader('Retry-After', '2')


def _provider_reason(body):
    """(provider_name, fixed_category, wire_tool) from an upstream error body.

    Only structural fragments leave this function: never raw bodies, schemas,
    argument values, secret-bearing text, or arbitrary upstream prose. The
    category is fixed wording chosen from the error shape; the offending tool
    is kept only after the bounded identity match below.
    """
    try:
        payload = json.loads(body.decode() if isinstance(body, bytes) else body)
    except (ValueError, UnicodeDecodeError, AttributeError):
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get('error')
    if not isinstance(error, dict):
        return None
    metadata = error.get('metadata')
    provider = metadata.get('provider_name') if isinstance(metadata, dict) else None
    raw = metadata.get('raw') if isinstance(metadata, dict) else None
    text = None
    if isinstance(raw, str):
        try:
            inner = json.loads(raw)
            text = inner.get('error') if isinstance(inner, dict) else raw
        except ValueError:
            text = raw
    if not isinstance(text, str):
        text = error.get('message') if isinstance(error.get('message'), str) else None
    if not isinstance(text, str) or not text.strip():
        return None
    tool = None
    match = re.search(r'\bns_[0-9a-f]{12}_\S+|\b[a-z][\w.-]*\.[\w-]+\b', text)
    if match:
        tool = match.group(0).rstrip(':,.')
    lowered = text.lower()
    if 'invalid_client_tool_schema' in lowered or 'must be an object' in lowered:
        reason = 'the tool schema was rejected'
    elif 'invalid' in lowered and 'tool' in lowered:
        reason = 'a tool call was rejected'
    else:
        reason = 'the request was rejected'
    return provider, reason, tool


def reject_opaque_agent_items(items):
    """Fail closed on unreadable encrypted briefs before any dispatch."""
    if comp.has_opaque_agent_item(items):
        raise PreparationError(
            'unsupported encrypted agent instructions; '
            'resend the assignment as plain text')


def validate_response(response, prepared):
    """Check adapted Responses encoding before forwarding response headers."""
    if prepared.provider in ('openai-subscription', 'openrouter') and prepared.tool_names:
        encoding = response.getheader('Content-Encoding', '').strip().lower()
        if encoding not in ('', 'identity'):
            raise ValueError('unsupported plaintext handoff response encoding')


def describe_failure(exc, response, info):
    """Name an upstream failure for the client: (status, message) or None.

    Pure: no reads, no logging, no clock. `response` is a snapshot
    {'status': int, 'body': bytes} or None when headers never arrived.
    Unknown shapes return None so the caller keeps existing behavior.
    """
    model = info.get('model', 'the model')
    timeout = info.get('timeout_s', 120)
    if response is not None:
        if response.get('status') == 429:
            return None  # existing Retry-After path owns 429s
        parsed = _provider_reason(response.get('body', b''))
        if parsed is None:
            return None
        provider, reason, tool = parsed
        who = f'upstream {provider}' if provider else 'upstream'
        message = (f'{model} was rejected by {who} '
                   f'(HTTP {response.get("status")}): {reason}. '
                   'Do not retry the unchanged request')
        if tool:
            message += f'; offending tool: {tool}'
        return 409, message
    if isinstance(exc, TimeoutError):
        elapsed = round((info.get('elapsed_ms') or 0) / 1000)
        message = (f'{model} did not answer within {timeout}s '
                   f'(waited {elapsed}s). Retry a shorter turn')
        if isinstance(model, str) and model.startswith('~x-ai/') and info.get('has_image'):
            message += '; Grok image turns stall upstream, retry text-only'
        return 502, message
    if isinstance(exc, OSError):
        host = info.get('host')
        if host:
            return 502, f'{model} is unreachable at {host}: check the network connection and retry'
        return 502, f'{model} lost its upstream connection before responding; retry'
    return None


def _passthrough(response):
    yield from passthrough(response)


class SubscriptionProvider:
    name = 'openai-subscription'
    host = 'chatgpt.com'

    def owns(self, model, path, openai_models, openai_mode='subscription'):
        if openai_mode == 'none':
            return False
        if path in NATIVE_SERVICE_PATHS:
            return True
        entry = by_slug(model) if isinstance(model, str) else None
        if entry is not None:
            return entry.provider == 'openai'
        return isinstance(model, str) and model in openai_models

    def prepare(self, model, path, payload, raw_body, headers, credentials):
        # The URL path token is the loopback auth; Codex >=0.153.4 omits the
        # subscription Authorization header, so forward client headers unchanged.
        fwd = {k: v for k, v in headers.items() if k.lower() not in HOP_HEADERS}
        try:
            names = agent_handoffs.add_plaintext_tools(payload) if path == '/responses' else set()
        except ValueError as exc:
            raise PreparationError(str(exc)) from exc
        if names:
            fwd = {k: v for k, v in fwd.items() if k.lower() not in ('content-encoding', 'accept-encoding')}
            fwd['Accept-Encoding'] = 'identity'
            raw_body = json.dumps(payload).encode()
        return Prepared(self.host, '/backend-api/codex' + path, fwd, raw_body, names, self.name)

    def adapt(self, response, tool_names, notes=None):
        if tool_names and response.status == 200:
            yield from agent_handoffs.adapt_response(response, tool_names, notes)
        elif notes is not None and response.status == 200:
            yield from snoop_response_identity(response, notes)
        else:
            yield from _passthrough(response)


class OpenRouterProvider:
    name = 'openrouter'
    host = OPENROUTER_HOST

    def owns(self, model, path, openai_models, openai_mode='subscription'):
        entry = by_slug(model) if isinstance(model, str) else None
        return entry is not None and entry.provider == 'openrouter' and path not in NATIVE_SERVICE_PATHS

    def prepare(self, model, path, payload, raw_body, headers, credentials):
        if path not in ('/responses', '/responses/compact'):
            raise PreparationError('OpenRouter supports responses only')
        # Contain before anything else: an opaque brief must never reach
        # credential lookup or upstream dispatch, where a child would infer
        # its assignment from inherited context instead.
        reject_opaque_agent_items(payload.get('input', []))
        # Scrub before prepare_tools: fragments KeyError its indexing, and
        # tool_search_output items (released-tool discovery) are never scrubbed.
        payload['input'] = comp.scrub_tool_fragments(payload.get('input', []))
        try:
            agent_handoffs.add_plaintext_tools(payload)
            tool_names = prepare_tools(payload)
            rewritten = comp.strip_reasoning_blobs(comp.rewrite_input(payload.get('input', [])))
        except ValueError as exc:
            raise PreparationError(str(exc))
        try:
            check_images(model, rewritten)
        except ValueError as exc:
            raise PreparationError(str(exc))
        keep_images = 'image' in input_modalities(model) if isinstance(model, str) else True
        entry = by_slug(model) if isinstance(model, str) else model
        payload['input'] = comp.note_images(rewritten) if getattr(entry, 'drop_images', False) else comp.strip_images(rewritten, keep_images)
        reasoning = payload.get('reasoning')
        try:
            check_effort(model,
                         reasoning.get('effort') if isinstance(reasoning, dict) else None)
        except ValueError as exc:
            raise PreparationError(str(exc))
        payload.pop('service_tier', None)
        if entry is None:
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
        if window:
            # Approximate input plus reserved output must fit. The typed
            # error lets the client mark context full and compact next turn.
            used = len(json.dumps(payload.get('input', []))) // 4
            reserved = payload['max_output_tokens']
            if used + reserved > window:
                raise ContextWindowExceeded(
                    f'request needs ~{used + reserved} tokens '
                    f'(~{used} input + {reserved} reserved output) '
                    f'but {(model if isinstance(model, str) else entry.slug)} allows {window}; compact or shorten the turn')
        return Prepared(self.host, '/api/v1/responses',
                        {'Authorization': 'Bearer ' + credentials.openrouter_key(),
                         'Content-Type': 'application/json', 'Accept-Encoding': 'identity'},
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
                adapter = ToolEvents(tool_names)
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
        body = {'model': model, 'input': [comp.user_message_item(prompt)],
                'max_output_tokens': 4000}
        levels = REASONING_LEVELS.get(model)
        if levels:
            # Never let default high effort burn the whole budget on reasoning.
            body['reasoning'] = {'effort': min(levels, key=CANONICAL_ORDER.index)}
        req = json.dumps(body).encode()
        conn = http.client.HTTPSConnection(OPENROUTER_HOST, timeout=120)
        try:
            conn.request('POST', '/api/v1/responses', body=req,
                headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
            resp = conn.getresponse()
            try:
                data = json.load(resp)
            except ValueError:
                raise OSError('Summarizer returned invalid JSON')
            return comp.extract_summary(resp.status, data)
        finally:
            conn.close()


class LocalServicesProvider:
    name = 'local-services'
    host = None

    def owns(self, model, path, openai_models, openai_mode='subscription'):
        return openai_mode == 'none' and path in NATIVE_SERVICE_PATHS

    def prepare(self, model, path, payload, raw_body, headers, credentials):
        local_services.answer(path)
        raise AssertionError('unreachable')

    def adapt(self, response, tool_names):
        raise AssertionError('unreachable')


PROVIDERS = (OpenRouterProvider(), SubscriptionProvider(), LocalServicesProvider())


def compaction_call(provider, model, path, payload):
    """Bound local serve for openrouter compact/V2-trigger turns, else None."""
    if provider.name != 'openrouter':
        return None
    if path == '/responses/compact':
        return lambda key: provider.compact(model, payload, key)
    if (path == '/responses'
            and comp.has_compaction_trigger(payload.get('input', []))):
        return lambda key: provider.compact_trigger(model, payload, key)
    return None


def select(model, path, openai_models=(), openai_mode='subscription'):
    for provider in PROVIDERS:
        if provider.owns(model, path, openai_models, openai_mode):
            return provider
    if openai_mode == 'none' and isinstance(model, str) and model in (openai_models or []):
        raise ValueError('Model is not available without a ChatGPT subscription')
    raise ValueError('Model is not in the configured catalog')
