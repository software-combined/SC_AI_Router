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
PREFIX = 'ocx1:'
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
    """Drop OpenAI-owned reasoning blobs other models cannot read; keep plaintext."""
    if not isinstance(items, list):
        return items
    out = []
    for item in items:
        if isinstance(item, dict) and item.get('type') == 'reasoning' and 'encrypted_content' in item:
            item = {k: v for k, v in item.items() if k != 'encrypted_content'}
            if not item.get('summary'):
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
        if 'encrypted_content' in item:
            return ''  # Provider-owned blob; never forward opaque content.
        return 'reasoning: ' + _block_text(item.get('summary', ''))[:2000]
    if is_compaction_item(item):
        return compaction_text(item)
    return ''

def transcript_for_summary(items):
    """Flatten user, assistant, tool and prior-compaction items, newest first."""
    if not isinstance(items, list):
        return ''
    kept, total = [], 0
    for item in reversed(items):
        text = _item_text(item)
        if not text.strip():
            continue
        if total + len(text) + 1 > TRANSCRIPT_BUDGET:
            break  # Keep the newest tail; a hole would strand old items.
        kept.append(text)
        total += len(text) + 1
    return '\n'.join(reversed(kept))

def extract_summary(status, data):
    """Pull summarizer text from a Responses payload; fail closed on bad shape."""
    if status != 200:
        raise OSError('Summarizer upstream failed')
    output = data.get('output') if isinstance(data, dict) else None
    if not isinstance(output, list):
        raise ValueError('Summarizer response has no output list')
    texts = []
    for item in output:
        if not isinstance(item, dict):
            raise ValueError('Summarizer output item is not an object')
        if item.get('type') == 'message':
            for block in item.get('content', []):
                if isinstance(block, dict) and block.get('type') in ('output_text', 'text') and block.get('text'):
                    texts.append(block['text'])
        elif item.get('type') == 'output_text' and item.get('text'):
            texts.append(item['text'])
    summary = '\n'.join(texts).strip()
    if not summary:
        raise ValueError('Compaction summary empty; retry compaction.')
    return summary
