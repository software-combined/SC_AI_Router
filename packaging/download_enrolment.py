"""Accept public sign-in settings only from a verified release or native package."""
import importlib.util
import json
import tempfile
from pathlib import Path


def _load(name):
    spec = importlib.util.spec_from_file_location(
        'router_enrolment_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def accept(home, config):
    """Existing installation-specific settings are never replaced implicitly."""
    if config is None:
        return False
    auth = _load('download_auth')
    home = Path(home)
    target = home / auth.CONFIG_FILE
    if target.exists() or target.is_symlink():
        auth.configure(home)
        return False
    with tempfile.TemporaryDirectory() as temporary:
        (Path(temporary) / auth.CONFIG_FILE).write_text(json.dumps(config))
        checked = auth.configure(temporary)
    _load('atomic_write').replace_json(target, checked)
    return True
