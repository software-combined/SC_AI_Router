"""Single source for retired subscription slugs (Plan 100).

Slugs withdrawn from the picker. ai_router/catalogue.py imports this leaf
normally and packaging/service.py spec-loads it (a package import would
break the installed launchers, which spec-load service before any sys.path
insert). Retiring a slug is one edit here. Plain frozenset, no annotations:
must stay parseable as Python 3.9 for the installer surface gate.
"""
SUBSCRIPTION = frozenset({'gpt-reserve', 'gpt-5.6-sol', 'gpt-5.6-luna'})
