"""Provider adapters. Each owns model membership, request preparation, upstream target and response adaptation."""
import http.client
import json
from . import compaction as comp, local_services
from .capabilities import CANONICAL_ORDER, OPENROUTER_HOST, REASONING_LEVELS, check_effort
from .registry import by_slug
from .runtime import log_event
from .tool_adapter import prepare_tools, stream_events, ToolEvents

HOP_HEADERS = {'host', 'connection', 'content-length', 'transfer-encoding',
               'upgrade', 'keep-alive', 'proxy-authorization', 'proxy-authenticate', 'te', 'trailer'}
NATIVE_SERVICE_PATHS = {'/alpha/search', '/alpha/notes/v2/thread_hint', '/guardian', '/guardian-classifier'}


class PreparationError(ValueError):
    """A well-formed request the provider cannot serve; maps to 409."""


class Prepared:
    __slots__ = ('host', 'path', 'headers', 'body', 'tool_names', 'provider')

    def __init__(self, host, path, headers, body, tool_names, provider):
        self.host, self.path, self.headers = host, path, headers
        self.body, self.tool_names, self.provider = body, tool_names, provider


def _passthrough(response):
    while chunk := response.read1(65536):
        yield chunk


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
        if not headers.get('Authorization', '').startswith('Bearer '):
            raise PermissionError('Codex subscription authentication required')
        fwd = {k: v for k, v in headers.items() if k.lower() not in HOP_HEADERS}
        return Prepared(self.host, '/backend-api/codex' + path, fwd, raw_body, set(), self.name)

    def adapt(self, response, tool_names):
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
        try:
            tool_names = prepare_tools(payload)
        except ValueError as exc:
            raise PreparationError(str(exc))
        payload['input'] = comp.strip_reasoning_blobs(comp.rewrite_input(payload.get('input', [])))
        reasoning = payload.get('reasoning')
        try:
            check_effort(model,
                         reasoning.get('effort') if isinstance(reasoning, dict) else None)
        except ValueError as exc:
            raise PreparationError(str(exc))
        payload.pop('service_tier', None)
        entry = by_slug(model) if isinstance(model, str) else model
        if entry is None:
            raise PreparationError(f'unknown model: {model}')
        limit = entry.max_output_tokens
        payload['max_output_tokens'] = min(payload.get('max_output_tokens') or limit, limit)
        return Prepared(self.host, '/api/v1/responses',
                        {'Authorization': 'Bearer ' + credentials.openrouter_key(),
                         'Content-Type': 'application/json'},
                        json.dumps(payload).encode(), tool_names, self.name)

    def adapt(self, response, tool_names):
        if tool_names and response.status == 200:
            if 'text/event-stream' in response.getheader('Content-Type', ''):
                yield from stream_events(response, tool_names)
            else:
                result = json.load(response)
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
            return comp.build_compact_v1_output(users, summary)
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


def select(model, path, openai_models=(), openai_mode='subscription'):
    for provider in PROVIDERS:
        if provider.owns(model, path, openai_models, openai_mode):
            return provider
    if openai_mode == 'none' and isinstance(model, str) and model in (openai_models or []):
        raise ValueError('Model is not available without a ChatGPT subscription')
    raise ValueError('Model is not in the configured catalog')
