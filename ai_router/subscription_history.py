"""Normalize replayed reasoning for the subscription Responses wire.

Foreign plaintext reasoning is not a portable saved item: keeping its id
without its content asks upstream to retrieve an item it never stored.
Only the outbound projection changes; the client's history stays intact.
"""


def normalize(payload):
    """Return the original payload on a no-op, otherwise a shallow copy."""
    items = payload.get('input')
    if not isinstance(items, list):
        return payload
    result = []
    changed = False
    for item in items:
        if (isinstance(item, dict) and item.get('type') == 'reasoning'
                and isinstance(item.get('content'), list) and item['content']):
            changed = True
            if item.get('encrypted_content'):
                result.append({key: value for key, value in item.items() if key != 'content'})
        else:
            result.append(item)
    return {**payload, 'input': result} if changed else payload
