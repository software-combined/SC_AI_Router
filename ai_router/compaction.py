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
from .agent_handoffs import recoverable_agent_message
from .compaction_result import IncompleteSummary as IncompleteSummary, extract_summary as extract_summary
from .history_portability import CALL_TYPES as CALL_TYPES, OUTPUT_TYPES as OUTPUT_TYPES, _block_text as _block_text, user_message_item as user_message_item
# Plan 183 phase 1 moved these to history_items and tool_runs; the old names
# stay importable here until phase 2 re-points their importers.
from .history_items import (REASONING_TEXT_BLOCKS as REASONING_TEXT_BLOCKS,
                            has_encryption_marked_agent_item as has_opaque_agent_item,
                            reasoning_text as _reasoning_text)
from .tool_runs import _call_complete as _call_complete, scrub_tool_fragments as scrub_tool_fragments
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
    except ValueError:
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
        else:
            rewritten.append(item)
    return rewritten


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

def _item_text(item):
    if not isinstance(item, dict):
        return ''
    kind = item.get('type')
    if kind == 'message':
        role = item.get('role', 'user')
        return f'{role}: {_block_text(item.get("content", ""))}'.strip()
    if kind in ('function_call', 'custom_tool_call', 'apply_patch_call'):
        label = item.get('name', 'apply_patch' if kind == 'apply_patch_call' else '')
        if item.get('namespace'):
            label = f"{item['namespace']}.{label}"
        return f'assistant tool call {label}: ' + str(item.get('arguments', item.get('input', item.get('operation', ''))))[:2000]
    if kind in ('function_call_output', 'custom_tool_call_output', 'apply_patch_call_output'):
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
        readable = recoverable_agent_message(item)
        if readable:
            item = {**item, 'content': readable}
        elif has_opaque_agent_item([item]):
            return ''
        author = item.get('author', 'agent') + (f' to {item["recipient"]}' if item.get('recipient') else '')
        text = _block_text(item.get('content', '')).strip() + ('\nEncrypted content was withheld from this external model. The result may be incomplete; request a plain-text resend if needed.' if readable else '')
        return f'{author}: {text}'.strip()
    return ''

TRUNCATED_NOTE = '[truncated] '


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
