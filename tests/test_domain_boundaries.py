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
    'ai_router/registry.py': ('router', 'providers', 'catalogue', 'models',
                                 'claude', 'setup', 'activation'),
    'ai_router/capabilities.py': ('router', 'providers', 'claude', 'setup'),
    'ai_router/compaction.py': ('router', 'providers'),
    'ai_router/tool_adapter.py': ('router', 'providers'),
    'ai_router/providers.py': ('router', 'claude'),
    'ai_router/transport.py': ('router', 'providers', 'claude', 'registry',
                                  'catalogue', 'models', 'setup'),
    'ai_router/protocols/__init__.py': ('router',),
    'ai_router/protocols/responses.py': ('router',),
    'ai_router/protocols/messages.py': ('router', 'providers'),
}


class DomainBoundaryTests(unittest.TestCase):
    def test_boundaries_hold(self):
        self.assertEqual(_check_rules(RULES), [])

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
