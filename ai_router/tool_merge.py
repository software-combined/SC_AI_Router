"""One keying rule for declared, released and recalled tool definitions.

`tool_adapter.prepare_tools` (live declarations plus released schemas) and
`discovered` (schemas recalled from the compaction cache) must agree on tool
identity and stub completion, or the effective tool set changes across a
restart. This leaf owns that rule and imports nothing.

The call sites keep their own policies where they genuinely differ:
prepare_tools never clobbers a declared definition and borrows only a missing
parameter schema, while this module's merge lets the first full definition
replace a bare stub.
"""


def key_of(tool, namespace=None):
    """Stable identity for one tool definition: (effective namespace, name).

    The caller supplies the effective namespace with no fallback:
    `merge_tool_defs` passes the wrapper name for wrapper-held tools and a
    flat row's own namespace field; `prepare_tools` passes the wrapper
    context only and None for top-level flat rows, exactly as before.
    """
    return namespace, tool.get('name')


def missing_schema(existing, candidate):
    """True when candidate holds the parameter schema an existing stub lacks."""
    return (existing.get('parameters') is None
            and candidate.get('parameters') is not None)


def complete_parameters(existing, candidate):
    """Borrow candidate's parameter schema into an existing stub, in place."""
    if not missing_schema(existing, candidate):
        return False
    existing['parameters'] = candidate['parameters']
    return True


def merge_tool_defs(defs):
    """One effective definition per (namespace, name) within one row shape.

    Flat rows and wrapper-held tools dedup independently; a flat row and
    a wrapper holding the same logical tool both survive (pre-existing
    mixed representation, harmless downstream).
    First occurrence wins.

    Fresh entries precede recalled ones in the input order, so the first
    full definition stands; a later entry supersedes an earlier one only
    to complete a stub that lacks parameters, mirroring prepare_tools.
    Namespace wrappers merge by their inner tools, never as one atomic
    row: two wrappers for the same namespace combine their tools instead
    of the newer wrapper discarding the older one."""
    merged = {}
    wrappers = {}
    order = []
    for tool in defs:
        if not isinstance(tool, dict):
            continue
        if tool.get('type') == 'namespace' and isinstance(tool.get('tools'), list):
            name = tool.get('name')
            if name not in wrappers:
                wrappers[name] = dict(tool, tools=[])
                order.append(('wrapper', name))
            for inner in tool.get('tools'):
                if not isinstance(inner, dict):
                    continue
                namespaced = dict(inner, namespace=tool.get('name'))
                key = key_of(namespaced, tool.get('name'))
                if key not in merged:
                    merged[key] = namespaced
                    wrappers[name]['tools'].append(namespaced)
                elif missing_schema(merged[key], namespaced):
                    merged[key] = namespaced
                    wrapped = wrappers[name]['tools']
                    for i, existing in enumerate(wrapped):
                        if key_of(existing, existing.get('namespace')) == key:
                            wrapped[i] = namespaced
            continue
        key = key_of(tool, tool.get('namespace'))
        if key not in merged or missing_schema(merged[key], tool):
            merged[key] = tool
        if key not in order:
            order.append(key)
    out = []
    for entry in order:
        if entry[0] == 'wrapper':
            wrapper = wrappers[entry[1]]
            if wrapper['tools']:
                out.append(wrapper)
        else:
            out.append(merged[entry])
    return out
