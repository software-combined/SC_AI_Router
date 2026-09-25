"""Rejected-request repair proposals for the Responses adapters (Plan 183 step 2.5).

A provider 400 is repaired only when the adapter that prepared the request can
say what the repair removes without changing what the turn means.
`ExternalResponsesProvider` proposes the annotation strip for an OpenRouter
400 that names no cause (no code, tool or parameter, not a context error).
`SubscriptionProvider` proposes the `invalid_encrypted_content` repair: the
OpenAI-owned reasoning blob goes, and the router's own compaction summary
becomes readable text.

A proposal only reads the prepared request and the bounded error body. It
opens no connection, reads no response, logs nothing, never sleeps and never
retries: `strip_retry` keeps the one-retry policy, the log lines and the send.
None means ineligible; a `Proposal` whose `prepared` is None means eligible
but unchanged, so the log line can tell the two apart.
"""
import io
import json
from collections import namedtuple
from compression import zstd

from . import provider_defs, subscription_history, transport, upstream

# `repair` names the log line's repair and `facts` are the structure-only
# diagnostics that line carries. `reports_rejection` asks the sender to log
# the rejection before retrying it: the subscription repair's live probe reads
# that line, while an external rejection is reported by the relay's verdict.
Proposal = namedtuple('Proposal', 'repair prepared facts reports_rejection')

_ANNOTATION_ONLY_FIELDS = frozenset((
    'client_metadata', 'prompt_cache_options', 'prompt_cache_key', 'metadata',
    'safety_identifier', 'store', 'include', 'service_tier', 'truncation',
    'background', 'top_logprobs', 'user', 'stream_options'))
# Matches runtime.MAX_DECODE_FACTOR without importing the composition root.
ZSTD_DECODE_LIMIT = 6 * transport.MAX_UPSTREAM_BODY


def annotation_strip(defn, prepared, described, raw):
    """The external proposal: annotation-only fields go for an unnamed 400."""
    unnamed = (defn.dialect == provider_defs.DIALECT_OPENROUTER
               and described is not None
               and described[2] is None
               and not upstream.is_context_error(raw)
               and upstream.rejection_tool(raw, defn.dialect) is None
               and upstream.rejection_parameter(raw) is None
               and upstream.rejection_reason(raw, defn.dialect)
               == 'the request was rejected')
    if not unnamed:
        return None
    return Proposal('annotation_strip',
                    _with_body(prepared, strip_annotations(prepared.body)), {}, False)


def encrypted_content(prepared, described, raw):
    """The subscription proposal for a 400 reporting `invalid_encrypted_content`.

    The subscription route forwards the reasoning blobs that
    `subscription_history.normalize` preserves, and the ChatGPT backend
    rejects a turn whose replayed blob it will not accept. Only this named
    condition is repaired, so a healthy or unrelated turn keeps its blobs.
    One scan serves both the diagnostics and the repair.
    """
    if (described is None or described[2] != 'invalid_encrypted_content'
            or upstream.is_context_error(raw)):
        return None
    content_encoding = next(
        (value for key, value in prepared.headers.items()
         if key.lower() == 'content-encoding'), '')
    payload, facts = _scan(prepared.body, content_encoding)
    body = None if payload is None else _strip_reasoning_payload(payload)
    if body is None:
        facts['removed'] = 0  # nothing was removed, so the line must say so
    return Proposal('reasoning_blobs', _with_body(prepared, body), facts, True)


def strip_annotations(body):
    """Remove annotation-only top-level fields; None when nothing would change."""
    payload = upstream.parse_payload(body)
    if payload is None:
        return None
    cut = {key: value for key, value in payload.items()
           if key not in _ANNOTATION_ONLY_FIELDS}
    if len(cut) == len(payload):
        return None
    return json.dumps(cut, separators=(',', ':')).encode('utf-8')


def _scan(body, content_encoding=None):
    """(payload, facts) for one wire body.

    `facts` is structure and state only: the observed `Content-Encoding` value,
    whether decoding and JSON parsing succeeded, whether `input` is a list, and
    counts of items, reasoning items and `encrypted_content` fields. It never
    carries item text, field values, blob bytes or any other content, so one
    `annotation_retry` line can explain an `outcome=unchanged` without logging
    the request.
    """
    encoding = (content_encoding or '').strip().lower()
    facts = {'encoding': encoding, 'decoded': False, 'parsed': False,
             'input_is_list': False, 'items': 0, 'reasoning_items': 0,
             'encrypted_fields': 0, 'removed': 0}
    raw = body
    if encoding == 'zstd':
        try:
            with zstd.ZstdFile(io.BytesIO(body)) as stream:
                raw = stream.read(ZSTD_DECODE_LIMIT + 1)
        except (OSError, EOFError, ValueError, zstd.ZstdError):
            return None, facts
        if len(raw) > ZSTD_DECODE_LIMIT:
            return None, facts
        facts['decoded'] = True
    elif encoding not in ('', 'identity'):
        return None, facts
    else:
        facts['decoded'] = True
    payload = upstream.parse_payload(raw)
    if payload is None:
        return None, facts
    facts['parsed'] = True
    items = payload.get('input')
    if not isinstance(items, list):
        return payload, facts
    facts['input_is_list'] = True
    facts['items'] = len(items)
    for item in items:
        if not isinstance(item, dict):
            continue
        facts['encrypted_fields'] += subscription_history.encrypted_field_count(item)
        if item.get('type') == 'reasoning':
            facts['reasoning_items'] += 1
        # `removed` counts the fields this repair takes out; a nested block or
        # an unowned item type is counted above and never removed.
        if subscription_history.removable_encrypted(item):
            facts['removed'] += 1
    return payload, facts


def _strip_reasoning_payload(payload):
    """The repaired body for the retry; None when nothing may change.

    `external_history.strip_reasoning_blobs` owns the field semantics: the
    blob goes, and an item left without readable reasoning text goes with it.
    A compaction item's unreadable summary blob becomes readable text instead,
    because the client replays that item and the backend cannot read it.
    """
    repaired = subscription_history.repair_input(payload.get('input'))
    if repaired is None:
        return None
    return json.dumps({**payload, 'input': repaired},
                      separators=(',', ':')).encode('utf-8')


def _with_body(prepared, body):
    """The prepared request carrying `body`; None when there is no body.

    Every non-body field is kept (tools, fallback plan, output cap, context
    size and the captured request context), and no header is added: the
    repaired body is plain JSON, so its `Content-Encoding` goes.
    """
    if body is None:
        return None
    headers = {key: value for key, value in prepared.headers.items()
               if key.lower() not in transport.HOP_HEADERS
               and key.lower() != 'content-encoding'}
    return transport.Prepared(prepared.host, prepared.path, headers,
                               body, prepared.tool_names, prepared.provider,
                               prepared.fallback, prepared.output_cap,
                               prepared.context_tokens, prepared.context)
