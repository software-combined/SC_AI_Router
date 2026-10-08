"""Real Codex media contract probe; synthetic upstream unless --live is explicit.

One generation send maximum. Live images use low quality and one image;
live videos use four seconds at 720p without audio. No polling or retries.
With --live-chat, allow at most three real chat sends and 2,048 output tokens
per send. Existing output files are refused before any paid call.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_router import catalogue, media, media_origin, provider_defs, registry, sse, transport
from ai_router.credentials import Credentials
from ai_router.protocols.images import POLICY as IMAGE_POLICY
from ai_router.router import Router
from tools.appserver_probe import AGENT_HANDOFFS, AppServer, codex_bin, scrub_env
from tools.probe_media import red_png

_spec = importlib.util.spec_from_file_location('media_client_config',
    ROOT / 'packaging/codex_switch_config.py')
_client_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_client_config)


def probe(model, live=False, variant='default', live_chat=False, output=None):
    if variant == 'subscription' and (live or live_chat):
        raise SystemExit('Native live media probes are retired; use the signed-in client directly.')
    row = registry.by_slug(model)
    if row is None or row.media_kind not in ('image', 'video'):
        raise ValueError('choose a registered media model')
    if row.media_kind == 'image' and model != 'openai/gpt-image-2':
        raise ValueError('the native Codex image tool selects GPT Image 2')
    if live and model not in ('openai/gpt-image-2', 'google/veo-3.1-fast'):
        raise ValueError('live budget permits GPT Image 2 or Veo 3.1 Fast only')
    if live_chat and (not live or row.media_kind != 'image'):
        raise ValueError('live chat requires a live image probe')
    if variant not in ('default', 'switched', 'subscription'):
        raise ValueError('choose default, switched or subscription client configuration')
    native = variant == 'subscription'
    if native and (live or row.media_kind != 'image'):
        raise ValueError('subscription probe permits only synthetic images')
    if output is not None and Path(output).exists():
        raise FileExistsError('choose a new output file before starting a probe')
    chat_model = _client_config._codex.DEFAULT_MODEL if row.media_kind == 'image' else model
    if native:
        chat_model = 'gpt-6-astra'
    calls, chat_calls, served, costs, items = [], [], [], [], []
    chat_served, chat_costs, copied = [], [], []
    upstream_statuses = []
    expected_result, retained = [], []
    image_origins = []
    send = transport.post_with_phases
    origin_route = IMAGE_POLICY.origin_route

    def bound_route(model, path, state, mode, payload, headers, turns, context):
        image_origins.append(media_origin.header(headers, 'x-codex-image-turn-id') is not None)
        return origin_route(model, path, state, mode, payload, headers, turns, context)

    def live_response(conn, prepared, metrics, identities, reported_costs):
        response, elapsed = send(conn, prepared, metrics)
        upstream_statuses.append(response.status)
        raw = transport.read_capped(response, transport.MAX_UPSTREAM_BODY)
        content_type = response.getheader('Content-Type', 'application/json')
        if 'text/event-stream' in content_type:
            docs = [json.loads(data) for _, data in sse.blocks(raw.splitlines(keepends=True))
                    if data and data != b'[DONE]']
            docs = [doc.get('response', {}) for doc in docs
                    if doc.get('type') == 'response.completed']
        else:
            docs = [json.loads(raw)]
        for doc in docs:
            if isinstance(doc, dict):
                if doc.get('model'):
                    identities.append(doc['model'])
                usage = doc.get('usage')
                if isinstance(usage, dict) and isinstance(usage.get('cost'), (float, int)):
                    reported_costs.append(usage['cost'])
        replay = media.Response(raw, content_type)
        replay.status = response.status
        return replay, elapsed

    def bounded_send(conn, prepared, metrics):
        body = json.loads(prepared.body)
        if prepared.provider != provider_defs.OPENAI.id and any(name.lower() in ('x-openai-actor-authorization', 'x-scg-codex-route',
                                'chatgpt-account-id') for name in prepared.headers):
            raise ValueError('private client headers reached an external send')
        if row.media_kind == 'image' and prepared.path.endswith('/responses'):
            if len(chat_calls) >= (3 if live_chat else 2):
                raise ValueError('chat call budget exhausted')
            # The native tool returns its 1024-square PNG in the next chat input.
            if transport.request_bytes(prepared) > 8 * 1024 * 1024:
                raise ValueError('chat input budget exceeded')
            chat_calls.append(prepared.path)
            if live_chat:
                body['max_output_tokens'] = 2048
                prepared.body = json.dumps(body).encode()
                prepared.decoded_body_bytes = len(prepared.body)
                return live_response(conn, prepared, metrics, chat_served, chat_costs)
            if len(chat_calls) == 1:
                name = next((tool['name'] for tool in body.get('tools', [])
                             if 'imagegen' in tool.get('name', '')
                             or native and tool.get('name') == 'image_gen'), None)
                if name is None:
                    raise ValueError('Codex did not expose its native image tool')
                item = {'type': 'function_call', 'id': 'fc_media_probe',
                        'call_id': 'call_media_probe', 'name': name,
                        'arguments': json.dumps({'prompt': 'A plain red square on a white background.',
                                                 'transparent_background': False})}
                if native:
                    item['name'] = 'imagegen'
                    item['namespace'] = 'image_gen'
                    item['status'] = 'completed'
            else:
                item = {'type': 'message', 'id': 'msg_media_probe', 'role': 'assistant',
                        'content': [{'type': 'output_text', 'text': 'Image created.'}]}
            answer = {'id': 'resp_media_probe_' + str(len(chat_calls)),
                      'model': body['model'], 'status': 'completed', 'output': [item]}
            events = [
                {'type': 'response.created', 'response': {**answer, 'output': []}},
                {'type': 'response.output_item.added', 'output_index': 0, 'item': item},
                {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                {'type': 'response.completed', 'response': answer}]
            raw = b''.join(sse.frame(json.dumps(event).encode()) for event in events)
            return media.Response(raw, 'text/event-stream'), time.monotonic()
        if calls:
            raise ValueError('media probe generation budget exhausted')
        defn = provider_defs.OPENAI if native else provider_defs.get(row.provider)
        expected = (defn.path_for(provider_defs.IMAGES, '/generations') if native else
                    media.images_path(defn) if row.media_kind == 'image' else media.videos_path(defn))
        image_model = 'gpt-image-2' if native else row.upstream_id or row.slug
        if prepared.path != expected or body.get('model') != image_model:
            raise ValueError('unexpected media destination or model')
        if transport.request_bytes(prepared) > 128 * 1024:
            raise ValueError('media probe input budget exceeded')
        if row.media_kind == 'image':
            body.update(n=1, quality='low', size='1024x1024')
        else:
            body.update(duration=4, resolution='720p', generate_audio=False)
        prepared.body = json.dumps(body).encode()
        prepared.decoded_body_bytes = len(prepared.body)
        calls.append(prepared.path)
        if live:
            replay, elapsed = live_response(conn, prepared, metrics, served, costs)
            doc = json.loads(replay.read())
            if row.media_kind == 'image':
                expected_result.append(hashlib.sha256(base64.b64decode(
                    doc['data'][0]['b64_json'], validate=True)).hexdigest())
            else:
                job = doc.get('data') if isinstance(doc.get('data'), dict) else doc
                expected_result.append(job['id'])
            replay.seek(0)
            return replay, elapsed
        doc = ({'created': 1, 'model': model,
                'data': [{'b64_json': base64.b64encode(red_png()).decode()}]}
               if row.media_kind == 'image' else
               {'id': 'synthetic-job', 'polling_url': '/api/v1/videos/synthetic-job',
                'status': 'pending', 'model': model})
        response = media.Response(json.dumps(doc).encode(), 'application/json')
        expected_result.append(hashlib.sha256(red_png()).hexdigest()
                               if row.media_kind == 'image' else doc['id'])
        response.status = 200 if row.media_kind == 'image' else 202
        return response, time.monotonic()

    with tempfile.TemporaryDirectory(prefix='codex-media-probe-') as folder:
        root = Path(folder)
        router_home = root / 'router'
        router_home.mkdir(mode=0o700)
        state = {'port': 0, 'token': 'synthetic-media-probe',
                 'openai_mode': 'subscription' if variant != 'default' else 'none',
                 'openai_models': [chat_model] if native else [], 'clients': []}
        if live:
            home = Path.home() / '.codex/mixed-model-router'
            saved = json.loads((home / 'mixed-router-state.json').read_text())
            key = Credentials(saved, home).key_for(row.provider)
            state['allowed_models'] = saved.get('allowed_models')
            state['openrouter_region'] = saved.get('openrouter_region', 'global')
        else:
            key = 'synthetic-media-key'
        path = router_home / 'openrouter.key'
        path.touch(mode=0o600)
        path.write_text(key)
        with mock.patch.dict(os.environ, {'ROUTER_HOME': str(router_home)}), \
                mock.patch.object(transport, 'post_with_phases', bounded_send), \
                mock.patch.object(IMAGE_POLICY, 'origin_route', bound_route), \
                mock.patch('ai_router.subscription_discovery.fetch_native', return_value=[]):
            router = Router(state, credentials=Credentials(state, router_home))
            threading.Thread(target=router.serve_forever, daemon=True).start()
            client_home = root / 'codex'
            client_home.mkdir(mode=0o700)
            if native and live:
                raise SystemExit('Native live media probes are retired; use the signed-in client directly.')
            state['port'] = router.server_port
            (client_home / 'config.toml').write_text(_client_config.build(
                router_home, state, state['openai_mode'], True, 'default' if native else variant))
            catalog_path = router_home / ('routed-models.json' if variant == 'switched'
                                          else 'mixed-models.json')
            catalog_path.write_text(json.dumps({'models': [
                catalogue.subscription_stub(chat_model) if native else
                catalogue.external_entry(registry.by_slug(chat_model))]}))
            config = {
                'model_providers.scg_router.request_max_retries': 0,
                'model_providers.scg_router.stream_max_retries': 0,
                'cli_auth_credentials_store': 'file',
                'model_reasoning_effort': 'low' if row.media_kind == 'image' else 'none',
                'features.enable_request_compression': False,
                'features.image_generation': True,
                'project_doc_max_bytes': 0, 'approval_policy': 'never',
                'sandbox_mode': 'read-only', 'web_search': 'disabled', 'mcp_servers': {}}
            if native:
                config.pop('model_providers.scg_router.request_max_retries')
                config.pop('model_providers.scg_router.stream_max_retries')
            for flag in ('apps', 'memories', 'plugins', 'shell_tool', 'multi_agent', 'code_mode',
                         'code_mode_only'):
                config['features.' + flag] = False
            command = [codex_bin(), 'app-server', '--stdio']
            for name, value in config.items():
                command += ['-c', name + '=' + json.dumps(value)]
            env = scrub_env(os.environ, AGENT_HANDOFFS, {'CODEX_HOME': str(client_home)})
            env.pop('OPENAI_API_KEY', None)
            client = AppServer(command, cwd=folder, env=env, stderr=subprocess.PIPE,
                               start_new_session=True, kill_group=True)
            try:
                client.rpc('initialize', {'clientInfo': {'name': 'media_probe', 'version': '1'},
                           'capabilities': {'experimentalApi': True}})
                client.send({'method': 'initialized', 'params': {}})
                account_absent = client.rpc('account/read', {'refreshToken': False}).get('account') is None
                if not native and not account_absent:
                    raise RuntimeError('external-only probe unexpectedly has a Codex account')
                thread = client.rpc('thread/start', {'model': chat_model, 'cwd': folder,
                    'approvalPolicy': 'never', 'sandbox': 'read-only', 'ephemeral': True,
                    'baseInstructions': 'Complete the synthetic media assignment.'})['thread']['id']
                client.rpc('turn/start', {'threadId': thread,
                    'input': [{'type': 'text', 'text': 'Generate one image of a plain red square '
                               'on a white background. Use the image tool once, then finish.',
                               'text_elements': []}]})
                deadline = time.monotonic() + 180
                while True:
                    event = client.next_event(deadline=deadline)
                    if event.get('method') == 'error':
                        if event.get('params', {}).get('willRetry'):
                            continue
                        raise RuntimeError('Codex rejected the media response: ' + str(
                            event.get('params', {}).get('error', {}).get('codexErrorInfo')))
                    if event.get('method') == 'item/completed':
                        item = event['params']['item']
                        items.append(item['type'])
                        if row.media_kind == 'image' and item['type'] == 'imageGeneration':
                            saved = Path(item.get('savedPath') or '').resolve()
                            if (item.get('status') == 'completed'
                                    and saved.is_relative_to(client_home.resolve())
                                    and saved.is_file()):
                                retained.append(hashlib.sha256(saved.read_bytes()).hexdigest())
                                if output is not None:
                                    destination = Path(output).resolve()
                                    destination.parent.mkdir(parents=True, exist_ok=True)
                                    with destination.open('xb') as artifact:
                                        artifact.write(saved.read_bytes())
                                    copied.append(str(destination))
                        elif row.media_kind == 'video' and item['type'] == 'agentMessage':
                            if expected_result and expected_result[0] in item.get('text', ''):
                                retained.append(expected_result[0])
                    if event.get('method') == 'turn/completed':
                        if event['params']['turn']['status'] != 'completed':
                            raise RuntimeError('Codex media turn did not complete')
                        break
                if len(calls) != 1:
                    raise RuntimeError('generation send was not observed')
                expected = 'imageGeneration' if row.media_kind == 'image' else 'agentMessage'
                if expected not in items or retained != expected_result:
                    raise RuntimeError('Codex did not retain the media result: ' + ','.join(items))
                if row.media_kind == 'image' and image_origins != [True]:
                    raise RuntimeError('Codex did not bind its image to the originating chat turn')
                return {'client_version': subprocess.check_output([codex_bin(), '--version'],
                    text=True).strip(), 'requested_model': model, 'requested_effort': 'none',
                    'served_models': served, 'served_effort': 'unverified', 'live': live,
                    'client_variant': variant, 'chatgpt_account_absent': account_absent,
                    'generation_provider': provider_defs.OPENAI.id if native else row.provider,
                    'generation_paths': calls, 'originating_image_turn_verified': image_origins == [True],
                    'requested_chat_model': chat_model,
                    'requested_chat_effort': 'low' if row.media_kind == 'image' else 'none',
                    'generation_calls': len(calls),
                    'synthetic_chat_calls': 0 if live_chat else len(chat_calls),
                    'live_chat_calls': len(chat_calls) if live_chat else 0,
                    'chat_served_models': chat_served, 'saved_images': copied,
                    'completed_items': items, 'retained_result_verified': True,
                    'reported_cost_usd': sum(costs + chat_costs) if costs or chat_costs else None,
                    'passed': True}
            except Exception:
                print(json.dumps({'diagnostic': 'media_probe_failure',
                    'generation_calls': len(calls), 'chat_calls': len(chat_calls),
                    'upstream_statuses': upstream_statuses, 'completed_items': items}),
                    file=sys.stderr)
                raise
            finally:
                client.close()
                router.shutdown()
                router.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--live-chat', action='store_true', help='also send capped real chat turns')
    parser.add_argument('--variant', choices=('default', 'switched', 'subscription'), default='default')
    parser.add_argument('--output', help='copy the retained image to a new file')
    args = parser.parse_args()
    try:
        print(json.dumps(probe(args.model, args.live, args.variant, args.live_chat, args.output)))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error_type': type(exc).__name__,
                          'reason': str(exc) if isinstance(exc, RuntimeError) else None}), file=sys.stderr)
        raise SystemExit(1)
