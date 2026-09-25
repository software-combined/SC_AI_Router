"""The external route's two tool stages alone, for declaration and history tests.

Runs `outbound`'s declaration then tool-history stages on one payload and
returns the prepared copy and the tool names. Without `row` it looks the payload's model up, a test
convenience only: the routed path always passes the request's captured row.
"""
from ai_router import outbound
from ai_router.registry import by_slug


def prepare_tools(payload, row=None):
    row = by_slug(payload.get('model', '')) if row is None else row
    projection = outbound.Projection('/responses', row=row)
    for stage in (outbound.declare_tools, outbound.rewrite_history):
        payload = stage(payload, projection)
    return payload, projection.names
