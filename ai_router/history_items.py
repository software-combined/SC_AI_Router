"""Shared vocabulary for replayed Responses history (Plan 183).

The tool call and output families, the readable-text readers and the
agent-message predicates that more than one outbound stage needs live here
once, so the stages that own each route cannot drift apart. It imports
nothing and only reads items; each stage decides what a match means for its
route.
"""


def block_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ' '.join(b.get('text', '') for b in content
            if isinstance(b, dict) and isinstance(b.get('text'), str))
    return str(content) if content else ''


def user_message_item(text):
    return {'type': 'message', 'role': 'user',
            'content': [{'type': 'input_text', 'text': text}]}


CALL_TYPES = frozenset({'function_call', 'custom_tool_call', 'apply_patch_call',
                        'web_search_call', 'file_search_call', 'image_generation_call',
                        'code_interpreter_call', 'computer_call'})
OUTPUT_TYPES = frozenset({'function_call_output', 'custom_tool_call_output',
                          'apply_patch_call_output'})
# A tool run is the call/output block of one assistant step. Nothing may be
# inserted inside it: a note between a parallel call and its output makes a
# strict upstream refuse the whole turn ("incomplete parallel tool-call
# group", measured on deepseek/deepseek-v4.1-flash 2026-09-13). The discovery
# pair keeps its names here because the portable pass may run on either side
# of the adapter rewrite that turns it into a plain function call.
TOOL_RUN_TYPES = CALL_TYPES | OUTPUT_TYPES | {'tool_search_call', 'tool_search_output'}


def summary_text(item):
    """Readable summary text only; a provider blob value is never read."""
    blocks = item.get('summary')
    if not isinstance(blocks, (str, list)):
        return ''
    return block_text(blocks).strip()


REASONING_TEXT_BLOCKS = frozenset({'reasoning_text', 'text'})


def reasoning_text(item):
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


# The two encrypted predicates disagree on an empty marker such as
# {'type': 'encrypted_content', 'encrypted_content': ''}: it marks an agent
# message, yet holds no payload, so it is never the encrypted sidecar of a
# recoverable reply. Each call site keeps its own predicate.
def has_encryption_marked_agent_item(items):
    """True when any agent item marks encrypted content, whatever the value."""
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


def holds_encrypted_payload(block):
    """True when a block carries a non-empty string or object payload."""
    payload = block.get('encrypted_content') if isinstance(block, dict) else None
    return bool(payload) and isinstance(payload, (str, dict))


def _readable_block(block):
    """A plaintext input_text block with no encrypted sidecar."""
    return (isinstance(block, dict) and block.get('type') == 'input_text'
            and 'encrypted_content' not in block and isinstance(block.get('text'), str)
            and bool(block['text'].strip()))


def inbound_agent_message(item):
    """True only for a strict child-to-parent message path."""
    author, recipient = item.get('author'), item.get('recipient')
    if not isinstance(author, str) or not isinstance(recipient, str):
        return False
    child = [part for part in author.split('/') if part]
    parent = [part for part in recipient.split('/') if part]
    return bool(parent) and len(child) > len(parent) and child[:len(parent)] == parent


def recoverable_agent_message(item):
    """Readable blocks of an inbound reply with an encrypted sidecar, else None."""
    if not inbound_agent_message(item) or 'encrypted_content' in item:
        return None
    content = item.get('content')
    if not isinstance(content, list) or not content:
        return None
    readable = [block for block in content if _readable_block(block)]
    encrypted = [block for block in content if holds_encrypted_payload(block)]
    return readable if readable and encrypted and len(readable) + len(encrypted) == len(content) else None


def plaintext_agent_message(item):
    """Represent a readable peer message without elevating its authority."""
    author, recipient = item.get('author'), item.get('recipient')
    content = item.get('content')
    if (not isinstance(author, str) or not author or not isinstance(recipient, str)
            or not recipient or not isinstance(content, list) or not content):
        raise ValueError('unsupported plaintext agent message shape')
    if 'encrypted_content' in item or not all(_readable_block(block) for block in content):
        raise ValueError('unsupported agent message content; use a fresh plaintext handoff')
    return {'type': 'message', 'role': 'assistant', 'content': [
        {'type': 'output_text', 'text': f'Agent message from {author} to {recipient}:\n'},
        *({'type': 'output_text', 'text': block['text']} for block in content)]}
