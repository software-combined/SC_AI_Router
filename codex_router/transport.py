"""Shared HTTP transport leaves (Plan 062). No policy, no model data.

Prepared, hop-header rules, raw stream iteration, and response header relay.
Transport never imports router, claude, registry, or the installer.
"""
import http.client  # noqa: F401 (re-exported for consumer call sites)


HOP_HEADERS = {'host', 'connection', 'content-length', 'transfer-encoding',
               'upgrade', 'keep-alive', 'proxy-authorization', 'proxy-authenticate', 'te', 'trailer'}


class Prepared:
    """Upstream target plus wire body. Built by protocol adapters."""

    __slots__ = ('host', 'path', 'headers', 'body', 'tool_names', 'provider')

    def __init__(self, host, path, headers, body, tool_names, provider):
        self.host, self.path, self.headers = host, path, headers
        self.body, self.tool_names, self.provider = body, tool_names, provider


def passthrough(response):
    while chunk := response.read1(65536):
        yield chunk


def relay_headers(response, send_header, model):
    """Forward upstream headers, pinning openai-model to the requested slug.

    Codex warns on any mismatch with the configured slug, so the upstream
    model name never goes out on that header; /health reports the real one.
    """
    for key, value in response.getheaders():
        if key.lower() in HOP_HEADERS or key.lower() in ('set-cookie', 'openai-model'):
            continue
        send_header(key, value)
    if isinstance(model, str):
        send_header('openai-model', model)
