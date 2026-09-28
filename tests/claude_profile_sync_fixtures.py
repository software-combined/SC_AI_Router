"""Shared synthetic fixtures for Claude profile session sync tests."""
import importlib.util
from pathlib import Path


def load_helper(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] /
                                                'packaging' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
