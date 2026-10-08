"""Bounded, content-free bindings from a Codex turn to its prepared connection."""
import json
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from .errors import PreparationError

TURN_TTL_S = 3600
MAX_TURNS = 1024
_IDENTIFIER = re.compile(r'[A-Za-z0-9_.-]{1,128}\Z')


def identifier(value):
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def header(headers, name):
    return next((value for key, value in headers.items() if key.lower() == name), None)


def turn_id(payload, headers):
    metadata = payload.get('client_metadata')
    if isinstance(metadata, dict) and identifier(metadata.get('turn_id')):
        return metadata['turn_id']
    raw = (metadata.get('x-codex-turn-metadata') if isinstance(metadata, dict)
           else None) or header(headers, 'x-codex-turn-metadata')
    if not isinstance(raw, str) or len(raw) > 16384:
        return None
    try:
        metadata = json.loads(raw)
    except ValueError:
        return None
    return identifier(metadata.get('turn_id')) if isinstance(metadata, dict) else None


@dataclass(frozen=True)
class Origin:
    provider: str
    context: object


class TurnRoutes:
    """No prompts, credentials, persisted history or last-active-model state."""

    def __init__(self):
        self._turns = OrderedDict()
        self._lock = threading.Lock()

    def remember(self, turn, prepared):
        context = prepared.context
        if not identifier(turn) or context is None or getattr(context.row, 'media_kind', None):
            return
        origin = Origin(prepared.provider, context)
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            previous = self._turns.get(turn)
            if previous and (previous[1] is None or
                    (previous[1].provider, previous[1].context.slug) !=
                    (origin.provider, context.slug)):
                origin = None
            self._turns[turn] = (now, origin)
            self._turns.move_to_end(turn)
            while len(self._turns) > MAX_TURNS:
                self._turns.popitem(last=False)

    def lookup(self, turn):
        with self._lock:
            self._prune(time.monotonic())
            entry = self._turns.get(identifier(turn))
            if entry is None or entry[1] is None:
                raise PreparationError('Image generation needs a known originating chat turn')
            return entry[1]

    def _prune(self, now):
        while self._turns and next(iter(self._turns.values()))[0] + TURN_TTL_S < now:
            self._turns.popitem(last=False)
