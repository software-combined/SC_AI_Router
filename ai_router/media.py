"""Media generation translation: Codex turns to the Images and Videos APIs.

Codex asks for pictures and clips inside a Responses turn (an
`image_generation`-style tool entry plus a text prompt). The image and
video models live behind OpenRouter's dedicated media endpoints, not the
chat route: `POST /api/v1/images` takes `{model, prompt, ...}` and
answers synchronously with base64 bytes, while `POST /api/v1/videos`
opens an async job the client polls. This module owns both translations
and both answer shapes; the adapters own targets, credentials and sends.

Video stays submit-only in this slice: the router hands Codex the job id
and polling URL and Codex polls the job route itself.
"""
import json

from . import provider_defs, request_evidence, transport
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
    for key in ('size', 'quality', 'n', 'output_format', 'background'):
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
    for key in ('duration', 'aspect_ratio', 'size', 'negative_prompt'):
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
    first = entries[0] if isinstance(entries[0], dict) else {}
    b64 = first.get('b64_json')
    if not isinstance(b64, str) or not b64:
        raise PreparationError('image upstream returned no picture bytes')
    created = doc.get('created') if isinstance(doc, dict) else None
    call = {'type': 'image_generation_call', 'status': 'completed',
            'result': b64}
    call['id'] = call_id or ('img_%s' % created if isinstance(created, int)
                             else 'img_generated')
    return {'model': model, 'status': 'completed', 'output': [call]}


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
    if not isinstance(job_id, str) or not isinstance(polling, str) or not polling:
        raise PreparationError('video upstream opened no job')
    return {'model': model, 'status': 'completed',
            'output': [{'type': 'message', 'role': 'assistant', 'content': [
                {'type': 'output_text',
                 'text': ('Video job %s is %s. Poll %s until completed, '
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
    headers.update(dict(adapter.defn.request_headers))
    raw = json.dumps(body).encode()
    return transport.Prepared(adapter.host, path, headers, raw,
                              ('media:' + kind,), adapter.name,
                              context=context, decoded_body_bytes=len(raw))


def adapt(response, tool_names):
    """Yield the media answer as one Responses body."""
    raw = transport.read_capped(response, transport.MAX_UPSTREAM_BODY)
    answer = image_answer if tool_names == ('media:image',) else video_answer
    try:
        model = request_evidence.identifier(json.loads(raw).get('model'))
    except ValueError:
        model = None
    yield json.dumps(answer(model or 'media', raw)).encode()
