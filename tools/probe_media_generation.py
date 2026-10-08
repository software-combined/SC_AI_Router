"""Real Codex media contract probe; synthetic upstream unless --live is explicit.

One generation send maximum. Live images use low quality and one image;
live videos use four seconds at 720p without audio. No polling or retries.
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_router import catalogue, media, provider_defs, registry, sse, transport
from ai_router.credentials import Credentials
from ai_router.router import Router
from tools.appserver_probe import AGENT_HANDOFFS, AppServer, codex_bin, scrub_env
from tools.probe_media import red_png


def probe(model, live=False):
    row = registry.by_slug(model)
    if row is None or row.media_kind not in ('image', 'video'):
        raise ValueError('choose a registered media model')
    if row.media_kind == 'image' and model != 'openai/gpt-image-2':
        raise ValueError('the native Codex image tool selects GPT Image 2')
    if live and model not in ('openai/gpt-image-2', 'google/veo-3.1-fast'):
        raise ValueError('live budget permits GPT Image 2 or Veo 3.1 Fast only')
    calls, chat_calls, served, costs, items = [], [], [], [], []
    expected_result, retained = [], []
    send = transport.post_with_phases

    def bounded_send(conn, prepared, metrics):
        body = json.loads(prepared.body)
        if row.media_kind == 'image' and prepared.path.endswith('/responses'):
            if len(chat_calls) >= 2:
                raise ValueError('synthetic chat budget exhausted')
            chat_calls.append(prepared.path)
            if len(chat_calls) == 1:
                name = next((tool['name'] for tool in body.get('tools', [])
                             if 'imagegen' in tool.get('name', '')), None)
                if name is None:
                    raise ValueError('Codex did not expose its native image tool')
                item = {'type': 'function_call', 'id': 'fc_media_probe',
                        'call_id': 'call_media_probe', 'name': name,
                        'arguments': json.dumps({'prompt': 'A plain red square on a white background.',
                                                 'transparent_background': False})}
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
        defn = provider_defs.get(row.provider)
        expected = media.images_path(defn) if row.media_kind == 'image' else media.videos_path(defn)
        if prepared.path != expected or body.get('model') != (row.upstream_id or row.slug):
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
            response, elapsed = send(conn, prepared, metrics)
            raw = transport.read_capped(response, transport.MAX_UPSTREAM_BODY)
            doc = json.loads(raw)
            if isinstance(doc, dict):
                if doc.get('model'):
                    served.append(doc['model'])
                usage = doc.get('usage')
                if isinstance(usage, dict) and isinstance(usage.get('cost'), (float, int)):
                    costs.append(usage['cost'])
            if row.media_kind == 'image':
                expected_result.append(hashlib.sha256(base64.b64decode(
                    doc['data'][0]['b64_json'], validate=True)).hexdigest())
            else:
                job = doc.get('data') if isinstance(doc.get('data'), dict) else doc
                expected_result.append(job['id'])
            replay = media.Response(raw, response.getheader('Content-Type', 'application/json'))
            replay.status = response.status
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
        state = {'port': 0, 'token': 'synthetic-media-probe', 'openai_mode': 'none',
                 'openai_models': [], 'clients': []}
        if live:
            home = Path.home() / '.codex/mixed-model-router'
            saved = json.loads((home / 'mixed-router-state.json').read_text())
            key = Credentials(saved, home).key_for(row.provider)
        else:
            key = 'synthetic-media-key'
        path = router_home / 'openrouter.key'
        path.touch(mode=0o600)
        path.write_text(key)
        with mock.patch.dict(os.environ, {'ROUTER_HOME': str(router_home)}), \
                mock.patch.object(transport, 'post_with_phases', bounded_send), \
                mock.patch('ai_router.subscription_discovery.fetch_native', return_value=[]):
            router = Router(state, credentials=Credentials(state, router_home))
            threading.Thread(target=router.serve_forever, daemon=True).start()
            client_home = root / 'codex'
            client_home.mkdir(mode=0o700)
            claims = {'https://api.openai.com/auth': {
                'chatgpt_account_id': 'synthetic-media-account', 'chatgpt_plan_type': 'plus'}}
            jwt = 'eyJhbGciOiJub25lIn0.' + base64.urlsafe_b64encode(
                json.dumps(claims).encode()).decode().rstrip('=') + '.synthetic'
            auth = {'auth_mode': 'chatgpt', 'OPENAI_API_KEY': None,
                    'tokens': {'id_token': jwt, 'access_token': 'synthetic-media-probe',
                               'refresh_token': 'synthetic-media-refresh'},
                    'last_refresh': datetime.now(timezone.utc).isoformat()}
            auth_path = client_home / 'auth.json'
            auth_path.touch(mode=0o600)
            auth_path.write_text(json.dumps(auth))
            chat_model = 'openai/gpt-6.1-sol' if row.media_kind == 'image' else model
            catalog_path = client_home / 'models.json'
            catalog_path.write_text(json.dumps({'models': [
                catalogue.external_entry(registry.by_slug(chat_model))]}))
            config = {'model_provider': 'probe_openai',
                'model_providers.probe_openai.name': 'OpenAI',
                'model_providers.probe_openai.base_url':
                    f'http://127.0.0.1:{router.server_port}/synthetic-media-probe/backend-api/codex',
                'model_providers.probe_openai.wire_api': 'responses',
                'model_providers.probe_openai.requires_openai_auth': True,
                'model_providers.probe_openai.supports_websockets': False,
                'model_providers.probe_openai.request_max_retries': 0,
                'model_providers.probe_openai.stream_max_retries': 0,
                'chatgpt_base_url': f'http://127.0.0.1:{router.server_port}/synthetic-media-probe',
                'cli_auth_credentials_store': 'file',
                'model_catalog_json': str(catalog_path),
                'model_reasoning_effort': 'low' if row.media_kind == 'image' else 'none',
                'project_doc_max_bytes': 0, 'approval_policy': 'never',
                'sandbox_mode': 'read-only', 'web_search': 'disabled', 'mcp_servers': {}}
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
                thread = client.rpc('thread/start', {'model': chat_model, 'cwd': folder,
                    'approvalPolicy': 'never', 'sandbox': 'read-only', 'ephemeral': True,
                    'baseInstructions': 'Complete the synthetic media assignment.'})['thread']['id']
                client.rpc('turn/start', {'threadId': thread,
                    'input': [{'type': 'text', 'text': 'A plain red square on a white background.',
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
                return {'client_version': subprocess.check_output([codex_bin(), '--version'],
                    text=True).strip(), 'requested_model': model, 'requested_effort': 'none',
                    'served_models': served, 'served_effort': 'unverified', 'live': live,
                    'generation_calls': len(calls), 'synthetic_chat_calls': len(chat_calls),
                    'completed_items': items, 'retained_result_verified': True,
                    'reported_cost_usd': sum(costs) if costs else None, 'passed': True}
            finally:
                client.close()
                router.shutdown()
                router.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(probe(args.model, args.live)))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error_type': type(exc).__name__,
                          'reason': str(exc) if isinstance(exc, RuntimeError) else None}), file=sys.stderr)
        raise SystemExit(1)
