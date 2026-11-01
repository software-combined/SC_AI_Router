"""The uncommitted attempt: which frames may wait for the retry decision.

Leaf for `stream_relay.py` (Plan 187). While the client holds nothing from an
attempt, a frame a retry would replace waits here instead of being written,
so a retried attempt leaves no second response identity behind and a final
one reaches the client in its original order, byte for byte. Anything that
cannot wait commits the attempt: the relay writes the hold, then that frame,
and from then on the attempt streams through and can no longer be retried.

Each kind waits in its own bounded place, so an echoing setup frame no
longer spends the budget the reasoning frames share:

- setup slots supplied by the decoder, in order and before any reasoning;
  Responses has two slots and Messages one; a duplicate or late one commits,
- one slot for a failure terminal carrying no output; one with output commits
  so that output never disappears into a retried attempt,
- `PENDING_LIMIT` bytes shared by reasoning and data-less frames.

A slot holds one frame, which the parser already caps at
`sse.MAX_FRAME_BYTES`, so one attempt retains at most three such frames plus
`PENDING_LIMIT`. That bounds retained wire bytes per stream, not the
process's memory: parsing and adapting each frame costs more on top.

Messages content, thinking and plumbing explicitly commit. Holding only
helps when re-sending the request is safe at all, which
`replay_safe` decides once per request from the tools it offers upstream.
"""
import json

from . import provider_defs, stream_events

# How many reasoning and data-less bytes one attempt may hold together.
PENDING_LIMIT = 65536

# Tool types the client runs after reading the stream. Preparation already
# turns client tool search and namespaced tools into plain functions
# (`tool_adapter.prepare_tools`), so these names cover every client tool. A
# hosted tool such as `web_search`, or any type not named here, may run
# upstream before the first frame, and a replay would run it again.
CLIENT_TOOL_TYPES = frozenset(('function', 'custom'))


def replay_safe(body, protocol=provider_defs.RESPONSES):
    """True when re-sending the prepared `body` cannot repeat upstream work.

    Decided from the tool types the provider was offered, never a model name:
    no tools, or only client-run ones. Messages uses input_schema and the
    custom type and requires stream=True. Unreadable is unsafe.
    """
    try:
        payload = json.loads(body)
        tools = payload.get('tools', [])
    except (ValueError, TypeError, AttributeError):
        return False
    if tools is None:
        tools = []
    if not isinstance(tools, list):
        return False
    if protocol == provider_defs.MESSAGES:
        if payload.get('stream') is not True:
            return False
        return all(isinstance(tool, dict) and tool.get('type') in (None, 'custom')
                   and isinstance(tool.get('input_schema'), dict)
                   and tool['input_schema'].get('type') == 'object' for tool in tools)
    return protocol == provider_defs.RESPONSES and all(
        isinstance(tool, dict) and tool.get('type') in CLIENT_TOOL_TYPES for tool in tools)


class AttemptHold:
    """The frames one attempt holds, in arrival order, and what they were."""

    __slots__ = ('frames', 'setup', 'shared', 'reasoning', 'terminal')

    def __init__(self):
        self.clear()

    def clear(self):
        """Release every held frame: flushed, replaced by a retry, or abandoned."""
        self.frames = []
        # Lifecycle kinds held so far, in order; a retry drops them all.
        self.setup = []
        # Bytes counted against PENDING_LIMIT, and the reasoning part of them,
        # folded into the record's counter only if a flush gets them out.
        self.shared = 0
        self.reasoning = 0
        # The writer of a held failure terminal, or None while none is held.
        self.terminal = None

    def size(self):
        return sum(len(frame) for frame in self.frames)

    def take(self, event):
        """Hold `event` and return True, or return False: the attempt commits."""
        if self.terminal is not None or event.commit:
            return False  # Nothing follows a verdict; a stray frame commits it.
        kind = event.kind
        if kind == stream_events.SETUP:
            if self.reasoning or event.setup_slot != len(self.setup):
                return False
            self.setup.append(event.setup_slot)
        elif kind == stream_events.FAILURE:
            if event.output:
                return False
            self.terminal = event.source
        elif kind in (stream_events.REASONING, stream_events.PLUMBING):
            if self.shared + len(event.frame) > PENDING_LIMIT:
                return False
            self.shared += len(event.frame)
            if kind == stream_events.REASONING:
                self.reasoning += len(event.frame)
        else:
            return False
        self.frames.append(event.frame)
        return True
