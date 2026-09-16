"""Client ids this router installs for (Plan 155).

Bare ids only, in one place: `clients/registry.py` gives each id its protocol
and its visibility rules, and `packaging/install.py` spec-loads this leaf by
path to derive its `--client`/`--clients` choices -- the same dual life
`ai_router/subscription_roster.py` has. Plain tuple, no annotations: stay
parseable as Python 3.9 and import nothing, so the installer never loads the
`ai_router` package.
"""
CLIENT_IDS = ('codex', 'claude')
DEFAULT_CLIENT = 'codex'
