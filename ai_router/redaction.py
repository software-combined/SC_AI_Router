"""Path redaction for diagnostics that must not name a filesystem location.

A leaf: it imports nothing from `ai_router`, so any module may use it without
widening its import graph.
"""
import re

_PART = r"[^\\/\s,;:'\"]+"        # one path segment, no separator or delimiter
_SPACED = rf"{_PART}(?:\s+{_PART})*"   # a segment that may contain spaces
_TAIL = rf"{_SPACED}?"
_PATH = re.compile(
    rf"(?<![\w:./])"                            # not inside a word, URL or path
    rf"(?:"
    rf"\\\\\?\\[A-Za-z]:\\(?:{_SPACED}\\)*{_TAIL}"      # \\?\C:\dir\file
    rf"|(?:\\\\|//)(?:{_SPACED}[\\/])+{_TAIL}"          # \\server\share or //server/share
    rf"|[A-Za-z]:\\(?:{_SPACED}\\)*{_TAIL}"             # C:\dir\file
    rf"|~?/(?:{_SPACED}/)*{_TAIL}"                      # /dir/file or ~/dir/file
    rf")")


def redact(text):
    """Replace filesystem paths in a diagnostic with a fixed marker.

    Error bodies and logs must stay useful without naming where a key or
    credential file lives. Path components may contain spaces; a trailing
    explanation after the path is kept.
    """
    if not isinstance(text, str):
        return text
    return _PATH.sub('[path]', text)
