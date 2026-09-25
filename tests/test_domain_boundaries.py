"""Plan 061: enforce domain ownership with stdlib ast.

A few high-value rules only, not a generic graph framework. Each rule names
the exact forbidden direction; the synthetic-violation check proves the
detector is not vacuous.
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _imports_of(path):
    tree = ast.parse(path.read_text())
    found = set()

    def _add(dotted):
        parts = dotted.split('.')
        found.add(parts[0])
        # Map the package prefix to the submodule: `from ai_router import
        # router` and `import ai_router.router` both mean a router import.
        if parts[0] == 'ai_router' and len(parts) > 1:
            found.add(parts[1])

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                if node.module:
                    # `from .providers import X` imports providers, not X.
                    found.add(node.module.split('.')[0])
                else:
                    for alias in node.names:
                        found.add(alias.name.split('.')[0])
            elif node.module:
                _add(node.module)
                if node.module.split('.')[0] == 'ai_router':
                    # `from ai_router import router` imports router.
                    for alias in node.names:
                        found.add(alias.name.split('.')[0])
    return found


def _check_rules(rules, root=ROOT):
    violations = []
    for rel, forbidden in rules.items():
        names = _imports_of(root / rel)
        for name in sorted(names & set(forbidden)):
            violations.append(f'{rel} imports {name}')
    return violations


# module -> local top-level names it must never import
RULES = {
    # Plan 141: the provider definition table is a leaf; it may import
    # nothing at all (also enforced by tests/test_provider_defs.py).
    'ai_router/provider_defs.py': ('router', 'providers', 'claude', 'registry',
                                    'catalogue', 'models', 'setup', 'credentials',
                                    'transport', 'capabilities'),
    'ai_router/registry.py': ('router', 'providers', 'catalogue', 'models',
                                 'claude', 'setup', 'activation'),
    'ai_router/capabilities.py': ('router', 'providers', 'claude', 'setup'),
    # Plan 183: compaction reads the vocabulary alone; the history stages
    # read its codec, so compaction never imports one of them back.
    'ai_router/compaction.py': ('router', 'providers', 'agent_handoffs',
                                'history_portability', 'external_history',
                                'subscription_history', 'standalone_outputs',
                                'tool_runs', 'outbound', 'jev_compaction'),
    # Plan 183: the shared history vocabulary is a leaf and the pairing model
    # sits on it alone, so neither may reach a stage that consumes them.
    'ai_router/history_items.py': ('router', 'providers', 'claude', 'compaction',
                                   'agent_handoffs', 'history_portability',
                                   'standalone_outputs', 'subscription_history',
                                   'tool_adapter', 'tool_runs', 'external_history'),
    'ai_router/tool_runs.py': ('router', 'providers', 'claude', 'compaction',
                               'agent_handoffs', 'history_portability',
                               'standalone_outputs', 'subscription_history',
                               'tool_adapter', 'jev_compaction', 'external_history'),
    'ai_router/tool_adapter.py': ('router', 'providers'),
    'ai_router/providers.py': ('router', 'claude'),
    'ai_router/claude.py': ('router', 'providers'),
    # Plan 165: upstream is wire/failure policy. It logs through the events
    # leaf, so it must never reach the boot graph (runtime, setup,
    # credentials, key_prompt) to write one line.
    'ai_router/upstream.py': ('router', 'claude', 'providers', 'transport',
                              'runtime', 'setup', 'credentials', 'key_prompt'),
    'ai_router/setup_page.py': ('router', 'providers', 'credentials', 'key_prompt'),
    # Plan 181: the wire contract only reads a body, so it stays below the
    # adapters, the transport and the boot graph that build and send one.
    'ai_router/wire_shape.py': ('router', 'providers', 'claude', 'transport',
                                'runtime', 'setup', 'credentials'),
    'ai_router/transport.py': ('router', 'providers', 'claude', 'registry',
                                  'catalogue', 'models', 'setup', 'runtime'),
    'ai_router/stream_errors.py': ('router', 'providers', 'claude', 'runtime',
                                   'setup'),
    'ai_router/protocols/__init__.py': ('router',),
    'ai_router/protocols/responses.py': ('router',),
    'ai_router/protocols/messages.py': ('router', 'providers'),
}


class DomainBoundaryTests(unittest.TestCase):
    def test_boundaries_hold(self):
        self.assertEqual(_check_rules(RULES), [])

    def test_leaf_modules_import_nothing_local_at_module_level(self):
        # Plan 165: `state` imports nothing local at all, and `events` is a
        # leaf whose only local import is the call-time `state.default_home`
        # inside configure_logging. tests/test_import_graph.py owns the
        # full-graph rules; this row keeps the intent beside the other
        # boundary rules.
        events = ast.parse((ROOT / 'ai_router' / 'events.py').read_text())
        local = [node for node in events.body
                 if isinstance(node, ast.ImportFrom) and node.level]
        self.assertEqual(local, [])

    def test_detector_rejects_a_synthetic_violation(self):
        # The check must fail when a rule is actually broken, not pass
        # vacuously because the AST walk misses the import form. A temp
        # fixture stands in for a future module that breaks a rule.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bad.py').write_text('from . import router\n')
            rules = {'bad.py': ('router',)}
            self.assertEqual(_check_rules(rules, root=root), ['bad.py imports router'])
            (root / 'good.py').write_text('import json\n')
            self.assertEqual(_check_rules({'good.py': ('router',)}, root=root), [])
            # The dominant repo idiom: `from .<module> import <name>`.
            (root / 'rel.py').write_text('from .providers import prepare_tools\n')
            self.assertEqual(_check_rules({'rel.py': ('providers',)}, root=root),
                             ['rel.py imports providers'])
            (root / 'abs.py').write_text('from ai_router import providers\n')
            self.assertEqual(_check_rules({'abs.py': ('providers',)}, root=root),
                             ['abs.py imports providers'])


if __name__ == '__main__':
    unittest.main()
