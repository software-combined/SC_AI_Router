"""Pure model metadata normalization (Plan 064). No command/client imports.

Vendor/name qualification, Codex modality projection, and refresh display
names. Consumed by models.py (new rows) and live_refresh.py (derived
fields). Must never import models, live_refresh, catalogue, providers,
installer, or clients.
"""

# Codex input vocabulary: change this one line if Codex widens InputModality.
CODEX_MODALITIES = ('text', 'image', 'audio')

VENDOR_BY_SLUG_PREFIX = {
    'anthropic': 'Anthropic', 'deepseek': 'DeepSeek', 'google': 'Google',
    'meta': 'Meta', 'moonshotai': 'MoonshotAI', 'openai': 'OpenAI',
    'qwen': 'Qwen', 'x-ai': 'SpaceXAI', 'z-ai': 'Z.ai',
}


def qualify_name(slug, live):
    """Qualified label (<Vendor>: <Short>) for one live metadata entry.

    Keeps any version/snapshot token verbatim, so a pinned row never
    masquerades as a tracking row; drops one redundant leading vendor word
    ("DeepSeek: DeepSeek V4 ..." -> "DeepSeek: V4 ..."). A live name without
    a vendor prefix falls back to the registry VENDOR_BY_SLUG_PREFIX map.
    """
    name = live.get('name', slug)
    vendor, sep, short = name.partition(':')
    if sep:
        vendor, short = vendor.strip(), short.strip()
    else:
        prefix = slug.split('/')[0].lstrip('~')
        vendor = VENDOR_BY_SLUG_PREFIX.get(prefix, prefix.replace('-', ' ').title())
        short = name
    first, _, rest = short.strip().partition(' ')
    if rest and first.rstrip('s').lower() == vendor.rstrip('s').lower().split()[-1]:
        short = rest
    return vendor, f'{vendor}: {short.strip()}'


def project_modalities(live_modalities):
    """Canonical Codex modalities advertised live, in canonical order."""
    return [m for m in CODEX_MODALITIES if m in (live_modalities or [])]


def refresh_display_name(row, live):
    """Qualified label for a refresh; alias rows keep their tracking name.

    A tilde alias (e.g. ~deepseek/...-latest) must keep the row's pinned
    tracking label ("... Latest") and never adopt the alias target's
    snapshot name ("... 0731"), so refreshes cannot reintroduce dated
    labels. Plain rows re-qualify from live metadata, keeping any version
    or snapshot token they advertise, but the vendor prefix stays pinned to
    the row: an upstream rebrand must not rewrite the label out from under
    the row's vendor field (such a rename is a registry edit, not a refresh).
    """
    alias = live.get('alias_target')
    alias = alias.get('name') if isinstance(alias, dict) else None
    if row['slug'].startswith('~'):
        return row.get('display_name')
    name = alias or live.get('name')
    if name:
        vendor, qualified = qualify_name(row['slug'], {'name': name})
        if vendor == row.get('vendor'):
            return qualified + ' \u00b7 OpenRouter'
    return row.get('display_name')
