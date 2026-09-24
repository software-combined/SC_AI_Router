"""Direct OpenRouter acceptance of replayed history shapes, one call per shape per row.

Offline (the default) builds each --shape body for each --model registry row
and prints the learnt contract's verdict on it, `wire_shape.violations` for
the OpenRouter dialect: rule names and counts only, and no request leaves
the machine. Default rows are the MiMo Flash and Muse Spark rows; default
shapes are all five.

--live sends each body straight to OpenRouter with no router in the path.
It needs --max-calls N (1-24) that covers every planned call, or it sends
nothing, and each call is one attempt that is never retried. The key
resolves the way the router's own does (`Credentials` over the router home
and its state), goes only into the request header and is never printed; the
state's data region picks the host. Every body caps output tokens and asks
for `low` effort where the row offers it. Each call prints one line: shape,
requested row, effort sent, HTTP status, served model, serving endpoint, and
whether a reply message carried the shape's marker. Never content.

Shapes, each ending where the model must answer from the half that holds the
marker (never the prompt or a call):
- custom_declared: a custom tool call and its output, the tool declared;
- custom_undeclared: the same pair with no tool declared;
- apply_patch: a completed `apply_patch_call` pair, undeclared, as the
  router forwards it for rows without freeform apply_patch;
- tool_search: a client tool search pair with the client's `tool_search`
  declaration, the marker in the released tool's description;
- reasoning: a carried reasoning item as the router forwards it (an id and
  reasoning text, its encrypted blob stripped), then the model's own answer
  carrying the marker and a request to repeat it.
"""
import argparse
import http.client
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_router import provider_defs, registry, upstream, wire_shape
from ai_router import state as router_state
from ai_router.credentials import Credentials

try:
    from tools import probe_standalone_outputs as standalone
except ImportError:  # run as a script: the sibling module is on sys.path
    import probe_standalone_outputs as standalone

ROWS = ('xiaomi/mimo-v2.6-flash', 'meta/muse-spark-1.3')
SHAPES = ('custom_declared', 'custom_undeclared', 'apply_patch', 'tool_search', 'reasoning')
MARKER = standalone.MARKER
# The per-call spend cap: the synthetic input is a few hundred tokens.
MAX_OUTPUT_TOKENS = 2048
_SERVED_MODEL = re.compile(r'[A-Za-z0-9_.:~/-]{1,80}')


def _user(text):
    return {'type': 'message', 'role': 'user', 'content': text}


def effort_for(entry):
    """`low` when the row offers it, else None so the row's default applies."""
    return 'low' if 'low' in entry.reasoning else None


def shape_body(shape, entry):
    """The Responses body one shape sends for one registry row."""
    prompt, tools = standalone.PAIR_PROMPT, []
    if shape in ('custom_declared', 'custom_undeclared'):
        items = standalone.shape_items('custom_pair')
        if shape == 'custom_declared':
            tools = [{'type': 'custom', 'name': items[0]['name'],
                      'description': 'Runs a synthetic command.'}]
    elif shape == 'apply_patch':
        items = standalone.shape_items('apply_patch_pair')
    elif shape == 'tool_search':
        released = {'type': 'namespace', 'name': 'probe', 'description': 'Synthetic lookup tools.',
                    'tools': [{'type': 'function', 'name': 'lookup',
                               'description': 'Returns ' + MARKER + '.',
                               'parameters': {'type': 'object', 'properties': {}}}]}
        items = [{'type': 'tool_search_call', 'call_id': 'call_probe_pair', 'execution': 'client',
                  'arguments': {'query': 'probe lookup'}},
                 {'type': 'tool_search_output', 'call_id': 'call_probe_pair', 'execution': 'client',
                  'status': 'completed', 'tools': [released]}]
        tools = [{'type': 'tool_search', 'execution': 'client', 'description': 'Finds synthetic tools.',
                  'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}},
                                 'required': ['query']}}]
    elif shape == 'reasoning':
        prompt = 'Name a synthetic marker.'
        items = [{'type': 'reasoning', 'id': 'rs_probe_replay', 'summary': [],
                  'content': [{'type': 'reasoning_text', 'text': 'The user wants a marker.'}]},
                 {'type': 'message', 'role': 'assistant',
                  'content': [{'type': 'output_text', 'text': MARKER}]},
                 _user('Repeat your previous answer exactly.')]
    else:
        raise ValueError('unknown shape: ' + str(shape))
    body = {'model': registry.upstream_id_for(entry), 'input': [_user(prompt), *items],
            'tools': tools, 'max_output_tokens': MAX_OUTPUT_TOKENS}
    if effort_for(entry):
        body['reasoning'] = {'effort': effort_for(entry)}
    return body


def row_entry(slug):
    """The registry row for an OpenRouter model; anything else exits."""
    entry = registry.by_slug(slug)
    if entry is None or entry.provider != provider_defs.DEFAULT_EXTERNAL:
        raise SystemExit(f'{slug} is not an OpenRouter registry row')
    return entry


def live_target():
    """(url, headers) for a direct call; the key lives only in the header."""
    home = router_state.default_home()
    saved = router_state.read(router_state.path(home)) or {}
    region = saved.get('openrouter_region', 'global')
    if not provider_defs.valid_region(region):  # the router refuses this state too
        raise SystemExit('the router state names an unknown OpenRouter region')
    host = provider_defs.region_host(provider_defs.DEFAULT_EXTERNAL, region)
    try:
        key = Credentials(saved, home).key_for(provider_defs.DEFAULT_EXTERNAL)
    except (LookupError, PermissionError, ValueError, OSError) as exc:
        raise SystemExit(f'no OpenRouter key: {exc}')
    defn = provider_defs.get(provider_defs.DEFAULT_EXTERNAL)
    headers = dict(defn.request_headers)
    headers.update({'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    return 'https://' + host + defn.path_for(provider_defs.RESPONSES, '/responses'), headers


def send(url, headers, body):
    """(HTTP status, parsed reply or None) for one attempt; None status on a transport failure."""
    request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers=headers, method='POST')
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as exc:
        response = exc  # a refusal still carries its status and error body
    except (OSError, http.client.HTTPException):
        return None, None
    with response:
        try:
            return response.status, upstream.parse_payload(response.read())
        except (OSError, http.client.HTTPException):
            return response.status, None


def carried_marker(reply):
    """True when a reply message's text holds the marker; reasoning never counts."""
    output = reply.get('output')
    for item in output if isinstance(output, list) else []:
        content = item.get('content') if isinstance(item, dict) and item.get('type') == 'message' else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and MARKER in str(block.get('text', '')):
                return True
    return False


def record(shape, entry, status, reply):
    """The one line a live call prints: names, codes and a flag, never content."""
    reply = reply or {}
    served = reply.get('model')
    return {'shape': shape, 'row': entry.slug, 'effort': effort_for(entry), 'status': status,
            'served_model': served if isinstance(served, str) and _SERVED_MODEL.fullmatch(served) else None,
            'serving_endpoint': upstream.serving_endpoint(reply),
            'marker': carried_marker(reply)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--model', action='append', help='OpenRouter registry row, repeatable')
    parser.add_argument('--shape', action='append', choices=SHAPES, help='repeatable')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--max-calls', type=int, default=0)
    args = parser.parse_args(argv)
    plan = [(row_entry(slug), shape) for slug in args.model or ROWS for shape in args.shape or SHAPES]
    if not args.live:
        for entry, shape in plan:
            found = wire_shape.violations(provider_defs.DIALECT_OPENROUTER, shape_body(shape, entry))
            print(json.dumps({'shape': shape, 'row': entry.slug, **found}))
        return 0
    if not 1 <= args.max_calls <= 24 or len(plan) > args.max_calls:
        raise SystemExit(f'--live needs --max-calls between 1 and 24 covering all {len(plan)} planned calls')
    url, headers = live_target()
    accepted = 0
    for entry, shape in plan:
        line = record(shape, entry, *send(url, headers, shape_body(shape, entry)))
        accepted += line['status'] == 200 and line['marker']
        print(json.dumps(line), flush=True)
    return 0 if accepted == len(plan) else 1


if __name__ == '__main__':
    sys.exit(main())
