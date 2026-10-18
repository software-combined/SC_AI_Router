"""The served instruction text and its rendered delegation roster (Plan 154).

Two assets: the routed text a model reached through a provider is served, and
the subscription text a ChatGPT-subscription row is served. Both carry the
same delegation block, whose roster line is rendered from the picker's own
visible rows and capped, so neither the text nor the merged catalogue grows
with the square of the roster. Leaf: no `ai_router` imports.
"""
from pathlib import Path

BASE_INSTRUCTIONS = (Path(__file__).with_name('routed_base_instructions.txt')).read_text(encoding='utf-8')
SUBSCRIBER_INSTRUCTIONS = (Path(__file__).with_name('subscription_base_instructions.txt')).read_text(encoding='utf-8')
SUBAGENT_MODEL_PLACEHOLDER = '{{SUBAGENT_MODEL_IDS}}'
MAX_ROSTER_IDS = 40
# Openings only this router's routed text has ever used. A stored template
# that carries one is the generator's own output, not an operator's wording,
# so a merge may replace it and `check` may refuse it (Plan 154). The second
# marker is the 0.6.75 phrasing an installed catalogue still holds.
ROUTED_MARKERS = ('running the selected routed model',
                  'running the selected OpenRouter model')


def is_routed_text(template):
    """True when a stored template is routed wording this router rendered."""
    return isinstance(template, str) and any(
        marker in template for marker in ROUTED_MARKERS)


def instructions_for(visible, client='codex', base=BASE_INSTRUCTIONS):
    """Served instructions with one roster line of visible model ids.

    The Codex client shows at most five spawn_agent model overrides, in
    catalogue order, so this line is how a routed session learns the ids it
    may still pass explicitly (Plan 151). Rendered from the picker's own
    projection, so a portco allowlist can never be widened by the text.
    Codex-only sentences start with "On Codex," and are omitted for Claude.
    Above MAX_ROSTER_IDS visible rows the line is truncated, which is what
    keeps the merged file from growing with the square of the roster (154).
    """
    ids = [model.slug for model in visible]
    roster = ', '.join(f'`{slug}`' for slug in ids[:MAX_ROSTER_IDS])
    if len(ids) > MAX_ROSTER_IDS:
        roster += (". The full list is in the router's own model listing")
    text = base.replace(SUBAGENT_MODEL_PLACEHOLDER, roster)
    if client != 'codex':
        text = '\n'.join(line for line in text.splitlines()
                         if not line.startswith('On Codex,'))
    return text
