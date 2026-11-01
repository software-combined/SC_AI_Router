"""Single source for the subscription-side picker roster (Plan 123).

Bare slugs that route on the ChatGPT subscription. packaging/service.py
spec-loads this leaf (a package import would break the installed launchers,
which spec-load service before any sys.path insert) and ai_router/catalogue.py
imports it normally; the per-slug presentation values stay in catalogue.py.
Plain tuple, no annotations: must stay parseable as Python 3.9 for the
installer surface gate.
"""
SUBSCRIPTION_SLUGS = ('gpt-6-astra', 'gpt-6-sol', 'gpt-5.6-terra',
                      'gpt-6-luna', 'gpt-5.5', 'gpt-5.4-mini',
                      'gpt-5.3-codex-spark', 'codex-auto-review')
# The registry row that serves the same model on the external provider, so a
# model whose subscription cannot run still has a paid route; the two list
# side by side and the twin carries the provider suffix in its label.
TWIN_PREFIX = 'openai/'

# Codex still sends helper-title turns on Luna 5.6 after the picker moves to
# Luna 6, so that legacy id stays routable (HELPER_SLUGS) while both retired
# ids map to their successors for roster migration (SUCCESSORS).
SUCCESSORS = {'gpt-5.6-sol': 'gpt-6-sol', 'gpt-5.6-luna': 'gpt-6-luna'}
HELPER_SLUGS = frozenset({'gpt-5.6-luna'})


def replace_successors(models):
    """Replace retired ids in place and deduplicate their successors."""
    replaced, seen = [], set()
    for model in models:
        if isinstance(model, str):
            model = SUCCESSORS.get(model, model)
            if model in seen:
                continue
            seen.add(model)
        replaced.append(model)
    return replaced
