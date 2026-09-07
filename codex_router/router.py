"""Local trial: retain Codex subscription authentication; isolate OpenRouter keys."""
import hmac
import http.client
import json
import io
import threading
import time
from compression import zstd
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .tool_adapter import prepare_tools, stream_events, ToolEvents
from .capabilities import OPENROUTER_HOST, OPENROUTER_MODELS
from . import compaction as comp

HOP_HEADERS = {'host', 'connection', 'content-length', 'transfer-encoding',
               'upgrade', 'keep-alive', 'proxy-authorization', 'proxy-authenticate', 'te', 'trailer'}
STATE = Path(__file__).with_name('mixed-router-state.json')
MAX_BODY = 16 * 1024 * 1024
# Fallback when a state file predates the cap key; explicit key wins when present.
DEFAULT_REQUEST_CAP = 1000
NATIVE_SERVICE_PATHS = {'/alpha/search', '/alpha/notes/v2/thread_hint', '/guardian', '/guardian-classifier'}

def prepare_openrouter(payload, path):
    if path not in ('/responses', '/responses/compact'):
        raise ValueError('OpenRouter supports trial responses only')
    payload['input'] = comp.rewrite_input(payload.get('input', []))
    payload.pop('service_tier', None)
    payload['max_output_tokens'] = min(payload.get('max_output_tokens') or 32768, 32768)
    return json.dumps(payload).encode()

def route(model, path, headers, openai_models, key):
    if path in NATIVE_SERVICE_PATHS:
        return ('chatgpt.com', '/backend-api/codex' + path,
                {k: v for k, v in headers.items() if k.lower() not in HOP_HEADERS})
    if model in OPENROUTER_MODELS:
        if path != '/responses':
            raise ValueError('OpenRouter supports trial responses only')
        return (OPENROUTER_HOST, '/api/v1/responses',
                {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    if model in openai_models:
        return ('chatgpt.com', '/backend-api/codex' + path,
                {k: v for k, v in headers.items() if k.lower() not in HOP_HEADERS})
    raise ValueError('Model is not in the configured catalog')

COMPACT_PROMPT = ('You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary '
    'for another LLM that will resume the task. Include: current progress and key decisions, '
    'important context/constraints/preferences, what remains with clear next steps, and any '
    'critical data or tool results needed to continue. Quote exact values, codes, names and '
    'tool results verbatim so the next model can repeat them exactly. Be concise and structured.')

def summarize_for_compact(model, key, payload_items):
    transcript = comp.transcript_for_summary(payload_items)
    prompt = COMPACT_PROMPT + '\n\nConversation:\n' + transcript
    req = json.dumps({'model': model, 'input': [comp.user_message_item(prompt)],
        'max_output_tokens': 2000}).encode()
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


class Router(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, state):
        super().__init__(('127.0.0.1', state['port']), Handler)
        self.state = state
        self.lock = threading.Lock()
        self.requests = 0

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass  # Request URLs and upstream credentials must never enter access logs.

    def error(self, status, message):
        body = json.dumps({'error': {'message': message, 'type': 'router_error'}}).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def authorized_path(self):
        prefix = '/' + self.server.state['token']
        candidate, sep, _ = self.path[1:].partition('/')
        if self.headers.get('Origin') or not sep or not hmac.compare_digest(candidate, self.server.state['token']):
            return None
        path = self.path[len(prefix):]
        return path.removeprefix('/backend-api/codex')

    def do_GET(self):
        path = self.authorized_path()
        if path is None:
            return self.error(403, 'Forbidden')
        if path == '/health':
            return self.error(200, 'Router ready')
        if self.headers.get('Upgrade', '').lower() == 'websocket':
            # Codex explicitly handles 426 by switching this session to HTTP/SSE.
            return self.error(426, 'Use HTTP streaming for this local trial')
        return self.error(404, 'Unsupported route')

    def do_POST(self):
        started = time.monotonic()
        path = self.authorized_path()
        if path is None:
            return self.error(403, 'Forbidden')
        if path not in NATIVE_SERVICE_PATHS | {'/responses', '/responses/compact'}:
            return self.error(404, 'Unsupported route')
        self.connection.settimeout(120)
        try:
            size = int(self.headers.get('Content-Length', '-1'))
            if size < 0 or size > MAX_BODY or self.headers.get('Transfer-Encoding'):
                return self.error(413, 'Invalid request size')
            body = self.rfile.read(size)
            encoding = self.headers.get('Content-Encoding', '')
            if encoding == 'zstd':
                with zstd.ZstdFile(io.BytesIO(body)) as stream:
                    decoded = stream.read(MAX_BODY + 1)
            else:
                decoded = body
            if len(decoded) > MAX_BODY:
                return self.error(413, 'Decoded request is too large')
            payload = json.loads(decoded)
            model = payload.get('model')
            if not isinstance(model, str) and path not in NATIVE_SERVICE_PATHS:
                return self.error(400, 'Missing model')
            key = ''
            custom_tools = set()
            if model in OPENROUTER_MODELS and path not in NATIVE_SERVICE_PATHS:
                try:
                    custom_tools = prepare_tools(payload)
                    body = prepare_openrouter(payload, path)
                except ValueError as exc:
                    return self.error(409, str(exc))
                with self.server.lock:
                    cap = self.server.state.get('request_cap', DEFAULT_REQUEST_CAP)
                    if self.server.requests >= cap:
                        return self.error(429, 'OpenRouter trial request cap reached; restart the local router to reset it.')
                    self.server.requests += 1
                auth = json.loads(Path(self.server.state['opencode_auth']).read_text())['openrouter']
                if auth['type'] != 'api':
                    raise ValueError('OpenCode credential is not an API key')
                key = auth['key']
            if model in OPENROUTER_MODELS and path == '/responses/compact':
                try:
                    # Request-cap above already covers this branch; summarizer is billable.
                    items = payload.get('input', [])
                    kinds, shapes = {}, {}
                    for _item in items if isinstance(items, list) else []:
                        kind = _item.get('type') if isinstance(_item, dict) else '?'
                        kinds[kind] = kinds.get(kind, 0) + 1
                        if isinstance(_item, dict):
                            shapes.setdefault(kind, set()).update(_item.keys())
                    print(json.dumps({'event': 'compact_started', 'model': model,
                                      'input_items': len(items) if isinstance(items, list) else -1,
                                      'item_kinds': kinds,
                                      'item_keys': {k: sorted(v) for k, v in shapes.items()}}), flush=True)
                    users = comp.extract_user_messages(items)
                    if not users:
                        raise ValueError('No user messages to compact')
                    summary = summarize_for_compact(model, key, items)
                    print(json.dumps({'event': 'compact_summarized', 'model': model,
                                      'summary_chars': len(summary)}), flush=True)
                    out = comp.build_compact_v1_output(users, summary)
                except ValueError as exc:
                    return self.error(409, str(exc))
                except (OSError, http.client.HTTPException):
                    return self.error(502, 'Compaction summarizer unavailable')
                body = json.dumps({'output': out}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True
                return
            host, upstream_path, headers = route(model, path, dict(self.headers),
                                                self.server.state['openai_models'], key)
            if host == 'chatgpt.com' and not self.headers.get('Authorization', '').startswith('Bearer '):
                return self.error(401, 'Codex subscription authentication required')
        except (ValueError, KeyError, OSError, TypeError, AttributeError, zstd.ZstdError):
            return self.error(400, 'Invalid model, payload, or local authentication configuration')
        conn = http.client.HTTPSConnection(host, timeout=120)
        sent = False
        metrics = {'provider': 'openai-subscription' if host == 'chatgpt.com' else 'openrouter',
                   'model': model, 'path': path, 'request_bytes': size,
                   'tool_definitions': len(payload.get('tools', [])),
                   'local_prepare_ms': round((time.monotonic() - started) * 1000, 1)}
        print(json.dumps({**metrics, 'event': 'request_started'}), flush=True)
        try:
            conn.request('POST', upstream_path, body=body, headers=headers)
            response = conn.getresponse()
            metrics['upstream_headers_ms'] = round((time.monotonic() - started) * 1000, 1)
            self.send_response(response.status)
            for k, v in response.getheaders():
                if k.lower() not in HOP_HEADERS and k.lower() != 'set-cookie':
                    self.send_header(k, v)
            self.send_header('Connection', 'close')
            self.end_headers()
            sent = True
            def chunks():
                if custom_tools and response.status == 200:
                    if 'text/event-stream' in response.getheader('Content-Type', ''):
                        yield from stream_events(response, custom_tools)
                    else:
                        result = json.load(response)
                        adapter = ToolEvents(custom_tools)
                        result['output'] = [adapter.item(item) for item in result.get('output', [])]
                        yield json.dumps(result).encode()
                else:
                    while chunk := response.read1(65536):
                        yield chunk
            for chunk in chunks():
                if 'first_chunk_ms' not in metrics:
                    metrics['first_chunk_ms'] = round((time.monotonic() - started) * 1000, 1)
                self.wfile.write(chunk)
                self.wfile.flush()
            print(json.dumps({**metrics, 'event': 'request_completed', 'status': response.status,
                              'total_ms': round((time.monotonic() - started) * 1000, 1)}), flush=True)
        except (OSError, http.client.HTTPException, ValueError, KeyError) as exc:
            print(json.dumps({**metrics, 'event': 'transport_error',
                              'error_type': type(exc).__name__,
                              'error_category': exc.msg if isinstance(exc, json.JSONDecodeError) else type(exc).__name__,
                              'total_ms': round((time.monotonic() - started) * 1000, 1)}), flush=True)
            if not sent:
                self.error(502, 'Upstream request failed')
        finally:
            conn.close()
            self.close_connection = True
