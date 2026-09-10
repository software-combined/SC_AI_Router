"""Single source for the subscription-side picker roster (Plan 123).

Bare slugs that route on the ChatGPT subscription. packaging/service.py
spec-loads this leaf (a package import would break the installed launchers,
which spec-load service before any sys.path insert) and ai_router/catalogue.py
imports it normally; the per-slug presentation values stay in catalogue.py.
Plain tuple, no annotations: must stay parseable as Python 3.9 for the
installer surface gate.
"""
SUBSCRIPTION_SLUGS = ('gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-terra',
                      'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4-mini',
                      'gpt-5.3-codex-spark', 'codex-auto-review')
