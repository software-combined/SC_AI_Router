"""A synthetic MCP server on stdio: N stub tools that echo the value given.

Both `tools/capture_claude_shapes.py` and `tools/probe_claude_code.py` need a
catalogue big enough to make Claude Code defer it, without a real connector.
The client launches this file as the server, speaks line-delimited JSON-RPC
over stdin and stdout, and calls `tool_000`..`tool_N`; `tools/call` returns
the caller's `value` so a probe can assert a unique marker made the round
trip.

Usage:
    python3.14 tools/mcp_stub_server.py --tools 700
"""
import argparse
import json
import sys

SERVER = 'stubtools'


def stub_tools(count):
    """The catalogue the server advertises; the client names them mcp__*."""
    return [{'name': 'tool_%03d' % index,
             'description': 'Synthetic stub tool %d; echoes the value given to it.'
                            % index,
             'inputSchema': {'type': 'object',
                             'properties': {'value': {'type': 'string'}},
                             'additionalProperties': False}}
            for index in range(count)]


def serve(count):
    """Answer initialize, tools/list and tools/call; ignore notifications."""
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        request_id = message.get('id')
        if request_id is None:
            continue
        method = message.get('method')
        params = message.get('params') or {}
        if method == 'initialize':
            result = {'protocolVersion': params.get('protocolVersion', '2024-11-05'),
                      'capabilities': {'tools': {}},
                      'serverInfo': {'name': SERVER, 'version': '1.0'}}
        elif method == 'tools/list':
            result = {'tools': stub_tools(count)}
        elif method == 'tools/call':
            value = (params.get('arguments') or {}).get('value')
            text = value if isinstance(value, str) else 'stub'
            result = {'content': [{'type': 'text', 'text': text}], 'isError': False}
        else:
            result = {}
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': request_id,
                                     'result': result}) + '\n')
        sys.stdout.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--tools', type=int, default=3,
                        help='tools the catalogue advertises')
    args = parser.parse_args(argv)
    serve(args.tools)
    return 0


if __name__ == '__main__':
    sys.exit(main())
