"""The routed-only Codex model list, `routed-models.json` beside the mixed list.

Switch Codex points Codex's picker at this file while Codex runs without
ChatGPT sign-in, so it must never offer a model that route cannot serve. It
holds the rows no-subscription mode shows (routed rows and their OpenAI twins,
no ChatGPT subscription rows) under the same key availability and portco
allowlist as `mixed-models.json`, and every availability sync rewrites it
beside that file. With no current snapshot, or no row left to show, the
previous file stays: Codex refuses an empty model list, and a list built for
no key would offer models this key cannot use.
"""
import json
from pathlib import Path

from . import catalogue
from .atomic_write import replace_json

NAME = 'routed-models.json'


def sync(home, available, allowed):
    """Rewrite the list from `available`, a live snapshot's id set; True when written."""
    if not available:
        return False
    merged = catalogue.merge({'models': []}, include_twins=True, allowed=allowed,
                             available=available)
    if not merged['models']:
        return False
    replace_json(Path(home) / NAME, merged)
    return True


def rows(home):
    """The list's rows, or () when the file is missing, unreadable or malformed."""
    try:
        models = json.loads((Path(home) / NAME).read_text()).get('models')
    except (OSError, ValueError, AttributeError):
        return ()
    if not isinstance(models, list) or not all(isinstance(row, dict) for row in models):
        return ()
    return tuple(models)
