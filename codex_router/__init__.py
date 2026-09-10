"""Deprecated alias: `codex_router` re-exports `ai_router`.

Kept so old releases, probes, and user scripts keep importing during the
transition window. New code imports `ai_router`. Removal needs its own plan.
"""
import importlib as _importlib
import sys as _sys

__path__ = _importlib.import_module('ai_router').__path__


def __getattr__(name):
    # Attribute access (`codex_router.registry`) resolves through the alias
    # so old code keeps working.
    target = _importlib.import_module(f'ai_router.{name}')
    globals()[name] = target
    _sys.modules[f'{__name__}.{name}'] = target
    return target


class _AliasFinder:
    # `import codex_router.registry` resolves through the alias too: the
    # import system asks this finder for `codex_router.<child>` and it
    # hands back the `ai_router.<child>` spec.
    def find_spec(self, fullname, path=None, target=None):
        if fullname == __name__ or not fullname.startswith(__name__ + '.'):
            return None
        return _importlib.machinery.PathFinder.find_spec(
            'ai_router' + fullname[len(__name__):], path=__path__)


_sys.meta_path.append(_AliasFinder())
