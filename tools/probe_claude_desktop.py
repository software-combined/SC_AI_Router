"""Opt-in bounded gateway for a synthetic task in the actual Claude desktop app."""
import argparse
import http.client
import json
import os
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_router import claude

lock = threading.Lock()
remaining = 4
allowed = 'deepseek/deepseek-v4.1-flash-1017'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, body):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split('?')[0] != prefix + '/v1/models':
            return self.reply(404, b'{}')
        conn = http.client.HTTPConnection('127.0.0.1', state['port'], timeout=10)
        conn.request('GET', prefix + '/v1/models')
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        for row in data['data']:
            row['id'] = claude.claude_alias(claude.resolve(row['id']))
        print(json.dumps({'event': 'listing', 'models': len(data['data'])}), flush=True)
        self.reply(200, json.dumps(data).encode())

    def do_POST(self):
        global remaining
        if self.path.split('?')[0] != prefix + '/v1/messages':
            return self.reply(404, b'{}')
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.reply(400, b'{}')
        if length > 262144 or length <= 0 or self.headers.get('Content-Encoding'):
            return self.reply(413, b'{"error":{"type":"invalid_request_error","message":"Probe input cap"}}')
        try:
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected object')
        except ValueError:
            return self.reply(400, b'{}')
        model = claude.resolve(body.get('model'))
        if model != allowed:
            return self.reply(400, b'{"error":{"type":"invalid_request_error","message":"Synthetic probe allows DeepSeek Flash only"}}')
        with lock:
            if remaining <= 0:
                return self.reply(400, b'{"error":{"type":"invalid_request_error","message":"Probe call cap reached"}}')
            remaining -= 1
            call = 4 - remaining
        body['model'] = model
        body['max_tokens'] = min(body.get('max_tokens', 2048), 2048)
        if body.get('thinking', {}).get('type') == 'enabled':
            body['thinking']['budget_tokens'] = min(body['thinking'].get('budget_tokens', 1024), 1024)
        print(json.dumps({'event': 'call', 'number': call, 'model': model,
                          'input_bytes': length, 'max_tokens': body['max_tokens']}), flush=True)
        conn = http.client.HTTPConnection('127.0.0.1', state['port'], timeout=90)
        conn.request('POST', prefix + '/v1/messages', json.dumps(body).encode(),
                     {'Content-Type': 'application/json', 'anthropic-version': '2023-06-01'})
        try:
            response = conn.getresponse()
            self.send_response(response.status)
            self.send_header('Content-Type', response.getheader('Content-Type', 'application/json'))
            self.end_headers()
            print(json.dumps({'event': 'response', 'number': call, 'status': response.status}), flush=True)
            for line in response:
                if line.startswith(b'data: '):
                    try:
                        event = json.loads(line[6:])
                        if event.get('type') == 'message_start':
                            print(json.dumps({'event': 'served', 'model': event.get('message', {}).get('model')}), flush=True)
                    except ValueError:
                        pass
                self.wfile.write(line)
                self.wfile.flush()
        finally:
            conn.close()


def main(argv=None):
    global state, prefix, remaining
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--home', type=Path,
                        default=Path.home() / '.codex/mixed-model-router')
    parser.add_argument('--endpoint-file', type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error('--execute is required for paid synthetic requests')
    state = json.loads((args.home / 'mixed-router-state.json').read_text())
    prefix = '/' + state['token']
    remaining = 4
    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        endpoint = 'http://127.0.0.1:%s%s' % (server.server_port, prefix)
        fd = os.open(args.endpoint_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(endpoint)
        print('Probe ready: 4 calls, 2048 output tokens and 256 KiB input per call.',
              flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if args.endpoint_file.exists() and args.endpoint_file.read_text() == endpoint:
                args.endpoint_file.unlink()


if __name__ == '__main__':
    main()
