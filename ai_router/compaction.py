"""Transparent compaction for routed models.

Adapted from OpenCodex MIT `src_responses_compaction.ts`: remote
compaction V2 wraps a plain summary as `ocx1:` + base64, decoded before
routed replay; V1 returns retained user messages plus one summary
message. Opaque native blobs stay visible as a note, never silently
dropped. Incomplete or failed summaries are rejected fail-closed.
"""
COMPACT_PROMPT = ('You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary '
    'for another LLM that will resume the task. Include: current progress and key decisions, '
    'important context/constraints/preferences, what remains with clear next steps, and any '
    'critical data or tool results needed to continue. Quote exact values, codes, names and '
    'tool results verbatim so the next model can repeat them exactly. Be concise and structured.')
import base64
import secrets
from .agent_handoffs import plaintext_agent_message
from .compaction_result import IncompleteSummary as IncompleteSummary, extract_summary as extract_summary
PREFIX = 'ocx1:'
TRIGGER_TYPE = 'compaction_trigger'
SUMMARY_PREFIX = ('Another language model started to solve this problem and '
    'produced a summary of its thinking process.')
OPAQUE_NOTE = ('[earlier conversation was compacted; the summary is stored '
    'in a format this model cannot read]')
COMPACTION_TYPES = {'compaction', 'compaction_summary', 'context_compaction'}
RETAINED_CHARS = 20000 * 4
TRANSCRIPT_BUDGET = 24000

def decode_summary(blob):
    if not isinstance(blob, str) or not blob.startswith(PREFIX):
        return None
    try:
        return base64.b64decode(blob[len(PREFIX):]).decode()
    except ValueError:  # UnicodeDecodeError and binascii.Error subclass it
        return None

def compaction_text(item):
    text = decode_summary(item.get('encrypted_content'))
    if text:
        return SUMMARY_PREFIX + '\n\n' + text
    return OPAQUE_NOTE

def is_compaction_item(item):
    return isinstance(item, dict) and item.get('type') in COMPACTION_TYPES


def has_compaction_trigger(items):
    """True when Codex opened remote-compaction V2 inline on /responses."""
    return (isinstance(items, list)
            and any(isinstance(item, dict) and item.get('type') == TRIGGER_TYPE
                    for item in items))


def encode_summary(summary):
    return PREFIX + base64.b64encode(summary.encode()).decode()


def v2_compaction_item(summary):
    """The exactly-one output item a V2 trigger turn must carry."""
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError('Compaction summary missing or empty; retry compaction.')
    return {'type': 'compaction', 'id': 'cmp_' + secrets.token_hex(8),
            'encrypted_content': encode_summary(summary.strip())}

def extract_user_messages(items):
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if not isinstance(item, dict) or item.get('role') != 'user':
            continue
        if item.get('type') not in (None, 'message'):
            continue
        content, text = item.get('content'), ''
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = ''.join(b.get('text', '') for b in content
                if isinstance(b, dict) and b.get('type') in ('input_text', 'text')
                and isinstance(b.get('text'), str))
        if text.strip():
            out.append(text)
    return out

def user_message_item(text):
    return {'type': 'message', 'role': 'user',
            'content': [{'type': 'input_text', 'text': text}]}


PORTABLE_SEARCH_NOTE = ('[tool search result replayed as declared tools; '
                        'the search call itself is omitted on this model]')
PORTABLE_REASONING_NOTE = '[reasoning summary from the previous model] '


def _summary_text(item):
    """Readable summary text only; a provider blob value is never read."""
    blocks = item.get('summary')
    if not isinstance(blocks, (str, list)):
        return ''
    return _block_text(blocks).strip()


def _has_model_switch(items):
    """True on the client's `<model_switch>` marker (first content block).

    The marker is a developer message the client writes on the first turn
    after a model swap; user text is data and never selects this path.
    """
    for item in items:
        if not isinstance(item, dict) or item.get('role') != 'developer':
            continue
        content = item.get('content')
        first = content[0] if isinstance(content, list) and content else None
        text = first.get('text') if isinstance(first, dict) else None
        if isinstance(text, str) and text.strip().startswith('<model_switch>'):
            return True
    return False


def portable_history(items, search_name, history_mode):
    """History a model switch cannot carry: the discovery pair and reasoning.

    Trigger: `history_mode == 'portable'` (the caller's registry quirk)
    or the client's `<model_switch>` marker. In that mode the search
    call/output matched by call_id collapses into one visible note; a
    half without its mate falls away so no orphan rides along, and
    discovery outputs ride nameless from the rewrite loop, so they join
    by call_id. A provider-scoped reasoning item never rides along: an
    upstream that did not produce it refuses the whole turn (Meta answers
    a carried reasoning item with a bare HTTP 400, measured 2026-09-12),
    so one with a readable summary replays as that visible note and one
    without is dropped.
    Released schemas stay declared in payload['tools']; every other item
    passes through.
    """
    if not isinstance(items, list):
        return items
    if history_mode != 'portable' and not _has_model_switch(items):
        return items
    calls = {item.get('call_id') for item in items
             if isinstance(item, dict) and item.get('type') == 'function_call'
             and item.get('name') == search_name and item.get('call_id')}
    matched = calls & {item.get('call_id') for item in items
                       if isinstance(item, dict)
                       and item.get('type') == 'function_call_output'
                       and (item.get('name') == search_name
                            or not item.get('name'))}
    out, noted = [], False
    for item in items:
        if not isinstance(item, dict):
            out.append(item)
            continue
        kind, name, call_id = item.get('type'), item.get('name'), item.get('call_id')
        if kind == 'reasoning':
            note = _summary_text(item)
            if note:
                out.append(user_message_item(PORTABLE_REASONING_NOTE + note[:2000]))
            continue
        discovery = ((kind == 'function_call' and name == search_name)
                     or (kind == 'function_call_output'
                         and (name == search_name or (not name and call_id in calls))))
        if not discovery:
            out.append(item)
        elif call_id in matched and not noted:
            out.append(user_message_item(PORTABLE_SEARCH_NOTE))
            noted = True
        # Unmatched halves and repeat matches fall away here.
    return out

def build_compact_v1_output(user_messages, summary):
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError('Compaction summary missing or empty; retry compaction.')
    selected, remaining = [], RETAINED_CHARS
    for msg in reversed(user_messages):
        if remaining <= 0:
            break
        if len(msg) <= remaining:
            selected.append(msg)
            remaining -= len(msg)
        else:
            selected.append(msg[len(msg) - remaining:])
            break
    selected.reverse()
    return [user_message_item(m) for m in selected] + [user_message_item(SUMMARY_PREFIX + '\n' + summary.strip())]

def rewrite_input(items):
    """Replace compaction items with visible text; never drop history silently."""
    if not isinstance(items, list):
        return items
    rewritten = []
    for item in items:
        if is_compaction_item(item):
            rewritten.append(user_message_item(compaction_text(item)))
        elif isinstance(item, dict) and item.get('type') == 'agent_message':
            rewritten.append(plaintext_agent_message(item))
        else:
            rewritten.append(item)
    return rewritten

# Calls the endpoint accepts, and outputs keyed by call. A fragment missing
# these fields (interrupted call, orphan output) 400s the whole turn, so the
# scrub drops fragments before anything is forwarded. A partial call never
# executed, so the next turn regenerates it if still needed. A standalone
# output (no call_id) is the app-injected instruction shape, not an orphan,
# and is never dropped here; providers materialize it before the scrub.
CALL_TYPES = frozenset({'function_call', 'custom_tool_call', 'apply_patch_call',
                        'web_search_call', 'file_search_call', 'image_generation_call',
                        'code_interpreter_call', 'computer_call'})
OUTPUT_TYPES = frozenset({'function_call_output', 'custom_tool_call_output',
                          'apply_patch_call_output'})


def _call_complete(item):
    kind = item.get('type')
    if not isinstance(item.get('call_id'), str):
        return False
    field = {'function_call': 'arguments', 'custom_tool_call': 'input'}.get(kind)
    if field is not None:
        return isinstance(item.get(field), str)
    if kind == 'apply_patch_call':
        return (item.get('status') in ('in_progress', 'completed')
                and isinstance(item.get('operation'), dict))
    return True


def scrub_tool_fragments(items):
    """Drop incomplete tool history; complete pairs pass through untouched."""
    if not isinstance(items, list):
        return items
    calls = {item.get('call_id') for item in items
             if isinstance(item, dict) and item.get('type') in CALL_TYPES
             and _call_complete(item)}
    out = []
    for item in items:
        if not isinstance(item, dict):
            out.append(item)
            continue
        kind = item.get('type')
        if kind in CALL_TYPES and not _call_complete(item):
            continue
        if (kind in OUTPUT_TYPES and isinstance(item.get('call_id'), str)
                and item['call_id'] not in calls):
            continue
        out.append(item)
    return out


REASONING_TEXT_BLOCKS = frozenset({'reasoning_text', 'text'})


def _reasoning_text(item):
    """Readable reasoning text; the provider blob value is never read."""
    parts = []
    for blocks, restricted in ((item.get('summary'), False), (item.get('content'), True)):
        if isinstance(blocks, str) and blocks.strip():
            parts.append(blocks.strip())
        elif isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if restricted and block.get('type') not in REASONING_TEXT_BLOCKS:
                    continue
                text = block.get('text')
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
    return ' '.join(parts)


def strip_reasoning_blobs(items):
    """Strip OpenAI-owned reasoning blobs; keep items that still hold readable text."""
    if not isinstance(items, list):
        return items
    out = []
    for item in items:
        if (isinstance(item, dict) and item.get('type') == 'reasoning'
                and 'encrypted_content' in item):
            item = {k: v for k, v in item.items() if k != 'encrypted_content'}
            if not _reasoning_text(item):
                continue
        out.append(item)
    return out

def _block_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ' '.join(b.get('text', '') for b in content
            if isinstance(b, dict) and isinstance(b.get('text'), str))
    return str(content) if content else ''

def _item_text(item):
    if not isinstance(item, dict):
        return ''
    kind = item.get('type')
    if kind == 'message':
        role = item.get('role', 'user')
        return f'{role}: {_block_text(item.get("content", ""))}'.strip()
    if kind in ('function_call', 'custom_tool_call'):
        label = item.get('name', '')
        if item.get('namespace'):
            label = f"{item['namespace']}.{label}"
        return f'assistant tool call {label}: ' + str(item.get('arguments', item.get('input', '')))[:2000]
    if kind in ('function_call_output', 'custom_tool_call_output'):
        label = f" {item['name']}" if item.get('name') else ''
        for key in ('output', 'result', 'content', 'text', 'data'):
            if item.get(key):
                return f'tool result{label}: ' + _block_text(item[key])[:2000]
        return ''
    if kind == 'reasoning':
        blob = item.get('encrypted_content')
        if isinstance(blob, str) and blob:
            return ''  # Real provider blob; opaque content never reaches summaries.
        text = _reasoning_text(item)
        return f'reasoning: {text}'[:2000] if text else ''
    if is_compaction_item(item):
        return compaction_text(item)
    if kind == 'agent_message':
        # Plaintext agent text survives compaction so follow-up scope is
        # retained. Anything encrypted stays out: the preparation guard owns
        # that rejection, and summaries must never launder opaque blocks.
        if has_opaque_agent_item([item]):
            return ''
        author = item.get('author', 'agent')
        if item.get('recipient'):
            author += f' to {item["recipient"]}'
        return f'{author}: {_block_text(item.get("content", ""))}'.strip()
    return ''

TRUNCATED_NOTE = '[truncated] '


def has_opaque_agent_item(items):
    """True when any agent item carries an unreadable encrypted block."""
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict) or item.get('type') != 'agent_message':
            continue
        if 'encrypted_content' in item:
            return True
        content = item.get('content')
        blocks = content if isinstance(content, list) else [content]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if 'encrypted_content' in block or block.get('type') == 'encrypted_content':
                return True
    return False


def transcript_for_summary(items):
    """Flatten user, assistant, tool and prior-compaction items, newest first."""
    if not isinstance(items, list):
        return ''
    kept, total, fallback = [], 0, ''
    for item in reversed(items):
        text = _item_text(item)
        if not text.strip():
            continue
        if not fallback:
            fallback = text  # Newest non-empty; tail-kept if nothing fits.
        if total + len(text) + 1 > TRANSCRIPT_BUDGET:
            break  # Keep the newest tail; a hole would strand old items.
        kept.append(text)
        total += len(text) + 1
    if kept:
        return '\n'.join(reversed(kept))
    if fallback:
        # One oversized newest message: keep its tail, never an empty brief.
        return TRUNCATED_NOTE + fallback[-(TRANSCRIPT_BUDGET - len(TRUNCATED_NOTE)):]
    return ''
