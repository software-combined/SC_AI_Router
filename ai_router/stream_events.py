"""What one external Responses frame is, decided once per frame (Plan 187).

Leaf beside `stream_errors.py`, which parses each frame and hands it here:
`classify` names the frame's lifecycle kind, and `StreamEvent` carries the
original frame bytes with that kind to `stream_attempt.py`, which decides
whether the frame may wait. The kinds are the contract every model on this
protocol inherits: nothing here reads a model name, and a frame this module
cannot place is `OPAQUE`, which the attempt forwards and so commits.

- `SETUP`: `response.created` / `response.in_progress` carrying no output and
  a status that has not finished. A retry replaces it.
- `REASONING`: reasoning items and reasoning text. A retry replaces it.
- `PLUMBING`: a frame with no data (an SSE comment or keep-alive).
- `ANSWER`: text, tool-call and other output items the client keeps.
- `FAILURE`: `response.failed`, `response.incomplete` or `error`; the verdict
  a retry may replace, with its writer in `source`.
- `COMPLETED`: a valid `response.completed`, which ends the attempt as a
  success. A malformed or error-bearing completion is `FAILURE`, so it can
  settle as a failure instead of silently becoming success.
- `OPAQUE`: malformed data, an unknown type, or a setup shape outside the
  rule above (output present, a finished status, no response object).
"""

SETUP = 'setup'
REASONING = 'reasoning'
PLUMBING = 'plumbing'
ANSWER = 'answer'
FAILURE = 'failure'
COMPLETED = 'completed'
OPAQUE = 'opaque'

# Answers, not plumbing: frames whose bytes the client cannot un-see. A
# response.created or reasoning frame before a failure costs nothing to
# replace, while a text or tool-call delta is output the client already has.
ANSWER_FRAME_TYPES = frozenset((
    'response.output_text.delta', 'response.output_text.done',
    'response.function_call_arguments.delta',
    'response.function_call_arguments.done',
    'response.reasoning_summary_text.delta', 'response.reasoning_summary_text.done',
    'response.custom_tool_call_input.delta', 'response.custom_tool_call_input.done',
))

# Reasoning a provider streams as text rather than as an item. The plan 177
# capture saw these from deepseek-v4.1-flash, and their bytes were unattributed
# before. Disjoint from ANSWER_FRAME_TYPES: a kind in both would be counted as
# content and as reasoning in the same frame.
REASONING_FRAME_TYPES = frozenset((
    'response.reasoning_text.delta', 'response.reasoning_text.done',
))

FAILURE_TYPES = frozenset(('response.failed', 'response.incomplete', 'error'))
# The order a provider opens a response in; `stream_attempt` holds each once.
SETUP_ORDER = ('response.created', 'response.in_progress')
_ITEM_TYPES = frozenset(('response.output_item.added', 'response.output_item.done'))
_UNFINISHED = frozenset((None, 'queued', 'in_progress'))
_COMPLETED_STATUSES = frozenset((None, 'completed'))


class StreamEvent:
    """One frame as the client will receive it, plus what it is.

    `frame` is the exact bytes to forward: the provider's own unless the
    documented refusal rewrite in `stream_errors` replaced them. `native` is
    the frame's own `type`, `source` names the writer of a `FAILURE` frame,
    and `output` is True when that terminal carries output items. `outcome`
    is the `outcome.Outcome` a terminal frame settles, else None.
    """

    __slots__ = ('frame', 'kind', 'native', 'source', 'output', 'outcome')

    def __init__(self, frame, kind, native=None, source=None, output=False,
                 outcome=None):
        self.frame = frame
        self.kind = kind
        self.native = native
        self.source = source
        self.output = output
        self.outcome = outcome


def _item_type(event):
    item = event.get('item')
    return item.get('type') if isinstance(item, dict) else None


def _unstarted(event):
    """A setup frame's response: an object with no output, not yet finished."""
    response = event.get('response')
    if not isinstance(response, dict):
        return False
    # An unhashable status (a list or object) must not reach the set lookup.
    status = response.get('status')
    return (response.get('output', []) == []
            and (status is None or isinstance(status, str))
            and status in _UNFINISHED)


def _completed_lifecycle(event):
    """A completion is success only when its response says it completed."""
    response = event.get('response')
    if not isinstance(response, dict) or not response or 'error' in event:
        return FAILURE
    if 'error' in response or response.get('status') == 'failed':
        return FAILURE
    output = response.get('output')
    if output is not None and (
            not isinstance(output, list)
            or not all(isinstance(item, dict) for item in output)):
        return FAILURE
    status = response.get('status')
    return (COMPLETED if status is None or (isinstance(status, str)
                                           and status in _COMPLETED_STATUSES)
            else FAILURE)


def classify(data, event):
    """The lifecycle kind of one frame from its data and parsed event.

    `event` is None when the data is not JSON. A reasoning item is
    replaceable: the client shows it, but a retried attempt supersedes it the
    same way it supersedes a setup frame, so it must not block a retry. An
    item frame with no type is neither, and commits as opaque.
    """
    if not data:
        return PLUMBING
    kind = event.get('type') if isinstance(event, dict) else None
    if not isinstance(kind, str):
        return OPAQUE  # No type, or one no set lookup can take (`[]`, `{}`).
    if kind in FAILURE_TYPES:
        return FAILURE
    if kind == 'response.completed':
        return _completed_lifecycle(event)
    if kind in SETUP_ORDER:
        return SETUP if _unstarted(event) else OPAQUE
    if kind in ANSWER_FRAME_TYPES:
        return ANSWER
    if kind in REASONING_FRAME_TYPES:
        return REASONING
    if kind in _ITEM_TYPES:
        item = _item_type(event)
        if item == 'reasoning':
            return REASONING
        if item is not None:
            return ANSWER
    return OPAQUE
