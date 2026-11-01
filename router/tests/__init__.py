"""Fast core suite by default; installer tests are opt-in (AGENTS.md 5)."""
import os
import unittest
from pathlib import Path

INSTALLER_TESTS = None  # lazy, single owner stays tools/ci_scope.py


def _installer_modules():
    global INSTALLER_TESTS
    if INSTALLER_TESTS is None:
        import importlib.util
        tool = Path(__file__).resolve().parents[1] / 'tools' / 'ci_scope.py'
        spec = importlib.util.spec_from_file_location('router_ci_scope', tool)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        INSTALLER_TESTS = frozenset(module.INSTALLER_TESTS)
    return INSTALLER_TESTS


def _leaves(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _leaves(item)
        else:
            yield item


def _module_of(test):
    module = getattr(test, '__module__', '') or ''
    if module == 'unittest.loader':
        # Loader-synthesized leaves (_FailedTest, ModuleSkipped) stay loud
        # in every suite; never attribute them to a skipped module.
        return ''
    return module


def load_tests(loader, tests, pattern):
    found = loader.discover(start_dir=str(Path(__file__).parent),
                            pattern=pattern or 'test*.py')
    if os.environ.get('SCG_RUN_INSTALLER_TESTS') == '1':
        tests.addTests(found)
        return tests
    skip = _installer_modules()
    tests.addTests(t for t in _leaves(found) if _module_of(t) not in skip)
    return tests
