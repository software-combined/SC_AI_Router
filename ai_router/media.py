"""Translate native Images requests and Responses video turns to media APIs.

The adapters own targets, credentials and sends. Images retain the native
Images envelope; videos return a job and authenticated polling URL.
"""
import io
import json
import secrets
from functools import partial

from . import provider_defs, request_evidence, sse, transport
from .errors import PreparationError

IMAGE_TOOL_TYPES = frozenset({'image_generation'})
VIDEO_TOOL_TYPES = frozenset({'video_generation'})


def _text_of(block):
    if not isinstance(block, dict):
        return ''
    kind = block.get('type')
    if kind in ('input_text', 'text'):
        text = block.get('text')
        return text.strip() if isinstance(text, str) and text.strip() else ''
    return ''


def prompt_from_input(items):
    """The picture/video prompt: text of the last user message, else ''."""
    prompt = ''
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        if item.get('role') != 'user':
            continue
        if item.get('type') not in (None, 'message'):
            continue
        prompt = ''  # Never reuse an earlier prompt after a textless user turn.
        content = item.get('content')
        if isinstance(content, str) and content.strip():
            prompt = content.strip()
            continue
        if isinstance(content, list):
            text = ' '.join(_text_of(block) for block in content).strip()
            if text:
                prompt = text
    return prompt


def media_tool(payload):
    """('image'|'video', tool entry) for a media tool turn, else (None, None)."""
    tools = payload.get('tools') if isinstance(payload, dict) else None
    if not isinstance(tools, list):
        return None, None
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        kind = tool.get('type')
        if kind in IMAGE_TOOL_TYPES:
            return 'image', tool
        if kind in VIDEO_TOOL_TYPES:
            return 'video', tool
    return None, None


def image_body(upstream_id, payload, tool):
    """Images-API body for one Codex turn; ValueError when no prompt."""
    prompt = prompt_from_input(payload.get('input', []))
    if not prompt:
        raise PreparationError('image generation needs a text prompt')
    body = {'model': upstream_id, 'prompt': prompt}
    for key in ('size', 'aspect_ratio', 'quality', 'n', 'output_format', 'background'):
        value = tool.get(key)
        if value is not None:
            body[key] = value
    return body


def video_body(upstream_id, payload, tool):
    """Videos-API submit body for one Codex turn; ValueError when no prompt."""
    prompt = prompt_from_input(payload.get('input', []))
    if not prompt:
        raise PreparationError('video generation needs a text prompt')
    body = {'model': upstream_id, 'prompt': prompt}
    for key in ('duration', 'aspect_ratio', 'size', 'resolution', 'generate_audio'):
        value = tool.get(key)
        if value is not None:
            body[key] = value
    return body


def image_answer(model, raw, call_id=None):
    """A Responses turn carrying the finished image_generation_call result.

    The native shape for a server-side image tool result: the item carries
    `id` (not `call_id`) with `status` completed and the base64 `result`,
    which is exactly what the history scrub keeps for the next turn.
    """
    try:
        doc = json.loads(raw)
    except ValueError:
        raise PreparationError('image upstream answered outside its envelope')
    entries = doc.get('data') if isinstance(doc, dict) else None
    if not isinstance(entries, list) or not entries:
        raise PreparationError('image upstream returned no picture')
    output = []
    for index, entry in enumerate(entries):
        b64 = entry.get('b64_json') if isinstance(entry, dict) else None
        if not isinstance(b64, str) or not b64:
            raise PreparationError('image upstream returned no picture bytes')
        output.append({'type': 'image_generation_call', 'status': 'completed',
                       'result': b64, 'id': (call_id if index == 0 and call_id
                                            else 'img_' + secrets.token_hex(8))})
    return {'model': model, 'status': 'completed', 'output': output}


def video_answer(model, raw):
    """A Responses turn carrying the async video job to poll."""
    try:
        doc = json.loads(raw)
    except ValueError:
        raise PreparationError('video upstream answered outside its envelope')
    job = doc.get('data') if isinstance(doc, dict) and isinstance(
        doc.get('data'), dict) else doc
    if not isinstance(job, dict):
        raise PreparationError('video upstream opened no job')
    job_id = job.get('id')
    polling = job.get('polling_url')
    if not isinstance(job_id, str) or not job_id or not isinstance(polling, str) or not polling:
        raise PreparationError('video upstream opened no job')
    return {'model': model, 'status': 'completed',
            'output': [{'type': 'message', 'id': 'msg_' + secrets.token_hex(8),
                        'role': 'assistant', 'content': [
                {'type': 'output_text',
                 'text': ('Video job %s is %s. Poll %s with your OpenRouter key until completed, '
                          'then download from %s/content.') % (
                              job_id, job.get('status') or 'pending',
                              polling, polling.rstrip('/'))}]}]}


def images_path(defn):
    return defn.path_for(provider_defs.IMAGES, '')


def videos_path(defn):
    return defn.path_for(provider_defs.VIDEOS, '')


MEDIA_TOOLS = (('media:image',), ('media:video',))


def is_media_tools(tool_names):
    """True for the marker tuple a media prepare stamps; never for chat maps."""
    return tool_names in MEDIA_TOOLS


def prepared(adapter, kind, tool, model, entry, payload, upstream_id,
             credentials, context):
    """Upstream target and wire body for one media turn on a media row."""
    del model, entry  # upstream_id already resolved; the row forked here.
    if kind == 'image':
        body = image_body(upstream_id, payload, tool)
        path = images_path(adapter.defn)
    else:
        body = video_body(upstream_id, payload, tool)
        path = videos_path(adapter.defn)
    headers = {'Authorization': 'Bearer ' + credentials.key_for(adapter.defn.id),
               'Content-Type': 'application/json',
               'Accept-Encoding': 'identity'}
    for key, value in adapter.defn.request_headers:
        if key.lower() not in ('authorization', 'content-type', 'accept-encoding'):
            headers[key] = value
    raw = json.dumps(body).encode()
    return transport.Prepared(adapter.host, path, headers, raw,
                              ('media:' + kind,), adapter.name,
                              context=context, decoded_body_bytes=len(raw),
                              response_adapter=partial(normalize, kind, upstream_id, adapter.host))


class Response(io.BytesIO):
    """A validated media answer with the client's Responses content type."""

    status = 200

    def __init__(self, body, content_type):
        super().__init__(body)
        self.content_type = content_type

    def getheaders(self):
        return [('Content-Type', self.content_type)]

    def getheader(self, name, default=None):
        return self.content_type if name.lower() == 'content-type' else default


def normalize(kind, model, host, response, streaming, notes):
    """Turn synchronous images or accepted video jobs into Responses output."""
    if response.status not in (200, 202):
        return response
    raw = transport.read_capped(response, transport.MAX_UPSTREAM_BODY)
    doc = json.loads(raw)
    request_evidence.observe(notes, doc, 'response.media')
    if kind == 'video' and isinstance(doc, dict):
        job = doc.get('data') if isinstance(doc.get('data'), dict) else doc
        polling = job.get('polling_url')
        if isinstance(polling, str) and polling.startswith('/'):
            job['polling_url'] = 'https://' + host + polling
        raw = json.dumps(doc).encode()
    answer = (image_answer if kind == 'image' else video_answer)(model, raw)
    answer.pop('model', None)  # A requested ID is not a provider identity report.
    answer.update(id='resp_' + secrets.token_hex(8), object='response')
    if not streaming:
        return Response(json.dumps(answer).encode(), 'application/json')
    events = [{'type': 'response.created', 'response': {**answer, 'status': 'in_progress', 'output': []}}]
    for index, item in enumerate(answer['output']):
        events.append({'type': 'response.output_item.added', 'output_index': index, 'item': item})
        events.append({'type': 'response.output_item.done', 'output_index': index, 'item': item})
    events.append({'type': 'response.completed', 'response': answer})
    body = b''.join(sse.frame(json.dumps(event).encode()) for event in events)
    return Response(body, 'text/event-stream')


def native_image_response(response, streaming, notes):
    """Validate the native Images result before Codex saves and displays it."""
    if response.status != 200:
        return response
    raw = transport.read_capped(response, transport.MAX_UPSTREAM_BODY)
    image_answer('media', raw)
    doc = json.loads(raw)
    if not isinstance(doc.get('created'), int):
        raise PreparationError('Image upstream returned no creation timestamp')
    request_evidence.observe(notes, doc, 'response.media')
    return Response(raw, 'application/json')
