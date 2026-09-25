"""One ordered outgoing Responses projection per route (Plans 183 and 188).

Each route's stages run in tuple order over one `Projection`: the facts the
adapter resolved (path, client model id, the request's captured row) plus
the values a later stage or the adapter reads back. A stage takes and returns
the payload; stages still edit it in place, as the adapters did, until Plan
183 phase 3 makes them copy-on-write. A ValueError from any stage is the
client's 400. The adapters keep destination, credentials, headers, body
encoding and the turn-size fit.
"""
from dataclasses import dataclass, field
from typing import Any

from . import agent_handoffs, compaction as comp, context_recovery, subscription_history
from .capabilities import check_row_effort
from .errors import PreparationError
from .image_items import note_images
from .registry import upstream_id_for
from .standalone_outputs import materialize_outputs, portable_replay
from .tool_adapter import prepare_tools
from .tool_history import SEARCH_NAME, rewrite_tool_history


@dataclass
class Projection:
    path: str
    model: Any = None  # the client's model id, named in a refusal
    row: Any = None  # the request's captured registry row; never looked up here
    handoffs: Any = field(default_factory=set)
    hinted: bool = False
    names: Any = None
    wire_names: Any = None


def contain(items):
    """Fail closed on unreadable encrypted briefs before any dispatch."""
    if isinstance(items, list) and any(
            comp.has_opaque_agent_item([item])
            and not agent_handoffs.recoverable_agent_message(item)
            for item in items):
        raise PreparationError(
            'unsupported encrypted agent instructions; '
            'resend the assignment as plain text')


def refuse_opaque_briefs(payload, p):
    # Contain before anything else: an opaque brief must never reach
    # credential lookup or upstream dispatch, where a child would infer
    # its assignment from inherited context instead.
    contain(payload.get('input', []))
    return payload


def recover_context(payload, p):
    return context_recovery.normalize(payload) if p.path == '/responses' else payload


def materialize_standalone(payload, p):
    # Standalone outputs (no call_id) are delegated messages, not orphans.
    payload['input'] = materialize_outputs(payload.get('input', []))
    return payload


def scrub_fragments(payload, p):
    # Scrub before prepare_tools: fragments KeyError its indexing, and
    # tool_search_output items (released-tool discovery) are never scrubbed.
    payload['input'] = comp.scrub_tool_fragments(payload.get('input', []))
    return payload


def add_handoff_tools(payload, p):
    p.handoffs = agent_handoffs.add_plaintext_tools(payload)
    return payload


def hint_lanes(payload, p):
    p.hinted = agent_handoffs.hint_full_lanes(payload)
    return payload


def declare_tools(payload, p):
    p.names, p.wire_names = prepare_tools(payload, p.row)
    p.names.handoffs = p.handoffs
    return payload


def rewrite_history(payload, p):
    rewrite_tool_history(payload, p.names, p.wire_names,
                         getattr(p.row, 'history_mode', None) if p.row else None)
    return payload


def compaction_text(payload, p):
    payload['input'] = comp.rewrite_input(payload.get('input', []))
    return payload


def strip_reasoning(payload, p):
    payload['input'] = comp.strip_reasoning_blobs(payload['input'])
    return payload


def note_media(payload, p):
    # One expression owns the wire rule: images pass only for an
    # image-capable row without drop_images; every other row gets the
    # visible note, including text-only rows with historical images.
    if not ('image' in getattr(p.row, 'modalities', ())
            and not getattr(p.row, 'drop_images', False)):
        payload['input'] = note_images(payload['input'])
    return payload


def check_effort(payload, p):
    reasoning = payload.get('reasoning')
    check_row_effort(p.row, reasoning.get('effort') if isinstance(reasoning, dict) else None)
    return payload


def drop_native_fields(payload, p):
    payload.pop('service_tier', None)
    # ChatGPT access-program enrolment is not an external-provider option.
    payload.pop('access_programs', None)
    return payload


def upstream_model(payload, p):
    if p.row is None:
        # Defence in depth: select()/owns() already refuses a slug that is
        # not a matching registry row, so this only fires for a direct
        # prepare() call and never for a routed request.
        raise PreparationError(f'unknown model: {p.model}')
    # The client id is the registry slug; the provider may expect another
    # id for the same model (Plan 153).
    payload['model'] = upstream_id_for(p.row)
    if getattr(p.row, 'provider_prefs', None):
        payload['provider'] = dict(p.row.provider_prefs)
    return payload


def output_cap(payload, p):
    limit = p.row.max_output_tokens
    window = getattr(p.row, 'context_window', 0) or 0
    if window:  # reservation counts against context; keep half for input
        limit = min(limit, window // 2)
    # Codex omits the cap and compacts at 90% of context. Its remaining
    # headroom must fit our default output, not the provider's maximum.
    default = min(32000, p.row.max_output_tokens)
    if window:
        default = min(default, window - window * 9 // 10)
    requested = payload.get('max_output_tokens')
    payload['max_output_tokens'] = min(requested, limit) if requested else default
    return payload


def replay_boundary(payload, p):
    return portable_replay(payload, SEARCH_NAME)


def replay_reasoning(payload, p):
    return subscription_history.normalize(payload)


EXTERNAL_STAGES = (
    refuse_opaque_briefs, recover_context, materialize_standalone, scrub_fragments,
    add_handoff_tools, hint_lanes, declare_tools, rewrite_history, compaction_text,
    strip_reasoning, note_media, check_effort, drop_native_fields, upstream_model,
    output_cap)
# A compaction request replays history but is offered no tools.
SUBSCRIPTION_REPLAY = (replay_boundary, replay_reasoning)
SUBSCRIPTION_STAGES = SUBSCRIPTION_REPLAY + (recover_context, add_handoff_tools, hint_lanes)


def _run(stages, payload, projection):
    try:
        for stage in stages:
            payload = stage(payload, projection)
    except PreparationError:
        raise
    except ValueError as exc:
        raise PreparationError(str(exc)) from exc
    return payload


def project_external(payload, path, model, row):
    """Payload and tool names for an external Responses turn on `row`."""
    projection = Projection(path, model, row)
    return _run(EXTERNAL_STAGES, payload, projection), projection.names


def project_subscription(payload, path):
    """Payload, handoff names and whether the client's body must be re-encoded."""
    stages = {'/responses': SUBSCRIPTION_STAGES,
              '/responses/compact': SUBSCRIPTION_REPLAY}.get(path, ())
    projection = Projection(path)
    projected = _run(stages, payload, projection)
    changed = projected is not payload or bool(projection.handoffs) or projection.hinted
    return projected, projection.handoffs, changed
