"""Bounded media generation for clients without a native media tool."""
import argparse
import base64
import http.client
import json
import os
import sys
import time
from pathlib import Path

from . import (availability, credentials, image_provider, media, media_origin,
               provider_defs, providers, request_context, state, transport)
from .errors import PreparationError
from .protocols.images import chat_provider

MAX_POLLS = 20
POLL_INTERVAL_S = 30
MAX_VIDEO_BYTES = 128 * 1024 * 1024


def exchange(prepared, method, path, body=None, cap=transport.MAX_UPSTREAM_BODY):
    conn = http.client.HTTPSConnection(prepared.host, timeout=transport.UPSTREAM_TIMEOUT_S)
    try:
        conn.request(method, path, body=body, headers=prepared.headers)
        response = conn.getresponse()
        if not 200 <= response.status < 300:
            raise PreparationError('Media provider refused the request (HTTP %d); no retry was sent' % response.status)
        if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
            raise PreparationError('Media provider returned an unsupported encoding')
        return transport.read_capped(response, cap)
    finally:
        conn.close()


def video_job(raw):
    doc = json.loads(raw)
    job = doc.get('data') if isinstance(doc, dict) and isinstance(doc.get('data'), dict) else doc
    if not isinstance(job, dict) or not media_origin.identifier(job.get('id')):
        raise PreparationError('Video provider returned no valid job ID')
    return job


def video_content(prepared, job):
    """Trusted host/path only, finite polls, and no second submission."""
    job_id = video_job(json.dumps(job))['id']
    path = prepared.path + '/' + job_id
    for _ in range(MAX_POLLS):
        status = job.get('status')
        if status == 'completed':
            raw = exchange(prepared, 'GET', path + '/content?index=0', cap=MAX_VIDEO_BYTES)
            if len(raw) < 12 or raw[4:8] != b'ftyp':
                raise PreparationError('Video provider returned no MP4 clip (job %s)' % job_id)
            return raw
        if status not in ('pending', 'in_progress'):
            raise PreparationError('Video generation stopped (job %s)' % job_id)
        time.sleep(POLL_INTERVAL_S)
        job = video_job(exchange(prepared, 'GET', path))
        if job['id'] != job_id:
            raise PreparationError('Video provider returned a different job ID')
    if job.get('status') == 'completed':
        raw = exchange(prepared, 'GET', path + '/content?index=0', cap=MAX_VIDEO_BYTES)
        if len(raw) >= 12 and raw[4:8] == b'ftyp':
            return raw
    raise PreparationError('Video polling limit reached; retain job %s and resume, do not submit again' % job_id)


def generate(kind, chat_model, model, prompt, output, config, creds, duration=4, job_id=None):
    if job_id is not None and (kind != 'video' or not media_origin.identifier(job_id)):
        raise PreparationError('Resume needs a valid video job ID')
    rows = request_context.capture()
    owner = chat_provider(chat_model, config, config.get('openai_mode', 'subscription'), rows)
    row = rows.get(model)
    if owner.kind != provider_defs.EXTERNAL:
        raise PreparationError('Use Codex native images for an OpenAI chat; native video is unavailable')
    if (row is None or row.media_kind != kind or row.provider != owner.name
            or config.get('allowed_models') is not None and model not in config['allowed_models']
            or not availability.permitted(model)):
        raise PreparationError('Choose an allowed media model on the chat provider')
    context = request_context.resolve(model, rows)
    if kind == 'image':
        provider = image_provider.ExternalImagesProvider(row,
            config.get('openrouter_region', 'global'), config.get('allowed_models'))
        payload = {'model': model, 'prompt': prompt, 'n': 1, 'quality': 'low',
                   'output_format': 'png', 'size': '1024x1024'}
        path = '/images/generations'
    else:
        provider = providers.select(model, '/responses', region=config.get('openrouter_region', 'global'),
            allowed=config.get('allowed_models'), catalogue=rows)
        payload = {'model': model, 'input': [{'role': 'user',
            'content': prompt or ('Resume existing job' if job_id else '')}],
            'tools': [{'type': 'video_generation', 'duration': duration,
                       'resolution': '720p', 'generate_audio': False}]}
        path = '/responses'
    prepared = provider.prepare(model, path, payload, b'', {}, creds, context=context)
    output = Path(output).absolute()
    # Reserve the destination before a paid submission; never replace an existing file.
    file = output.open('xb')
    job = None
    try:
        with file:
            if kind == 'video':
                job = ({'id': job_id, 'status': 'pending'} if job_id else
                       video_job(exchange(prepared, 'POST', prepared.path, prepared.body)))
                print(json.dumps({'status': 'resuming' if job_id else 'accepted', 'job_id': job['id']}),
                      file=sys.stderr, flush=True)
                raw = video_content(prepared, job)
            else:
                reply = media.Response(exchange(prepared, 'POST', prepared.path, prepared.body), 'application/json')
                answer = json.loads(media.native_image_response(reply, False, {}).read())
                raw = base64.b64decode(answer['data'][0]['b64_json'], validate=True)
                if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise PreparationError('Image provider returned no PNG image')
            file.write(raw)
            file.flush()
            if not os.path.samefile(output, file.fileno()):
                raise PreparationError('Media output path changed before completion')
    except BaseException as exc:
        # Another writer may replace the reserved path while polling; never unlink it.
        if job is not None and isinstance(exc, (OSError, ValueError, LookupError, http.client.HTTPException)):
            raise PreparationError('Video result was not saved; retain job %s and resume with a new output path, do not submit again'
                                   % job['id']) from exc
        raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('image', 'video'))
    parser.add_argument('--chat-model', required=True)
    parser.add_argument('--model')
    parser.add_argument('--prompt', default='')
    parser.add_argument('--output', required=True)
    parser.add_argument('--duration', type=int, choices=(4, 6, 8), default=4)
    parser.add_argument('--job-id')
    args = parser.parse_args()
    home = state.default_home()
    config = state.read_strict(state.path(home))
    model = args.model or ('openai/gpt-image-2' if args.kind == 'image' else 'google/veo-3.1-fast')
    try:
        creds = credentials.Credentials(config, home)
        row = request_context.capture().get(model)
        if row is not None and provider_defs.is_external(row.provider):
            availability.restore(home, creds.key_for(row.provider), config.get('openrouter_region', 'global'))
        result = generate(args.kind, args.chat_model, model, args.prompt, args.output,
                          config, creds, args.duration, args.job_id)
    except (OSError, ValueError, LookupError, http.client.HTTPException) as exc:
        message = str(exc) if isinstance(exc, PreparationError) else 'Media request failed; no automatic retry was sent'
        parser.exit(1, message + '\n')
    print(json.dumps({'status': 'completed', 'path': str(result)}))


if __name__ == '__main__':
    main()
