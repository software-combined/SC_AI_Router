"""Compatibility entry point for older Switch Claude shortcuts."""
import importlib.util
from pathlib import Path


def _stable():
    path = Path(__file__).with_name('claude_profile_launch.py')
    spec = importlib.util.spec_from_file_location('claude_profile_launch', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_launch = _stable()
helper_path = _launch.helper_path
main = _launch.main


if __name__ == '__main__':
    main()
