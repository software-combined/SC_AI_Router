"""Installer-side name for the shared atomic writer (Plan 131).

The leaf lives in ai_router/atomic_write.py so the runtime and the installer
share one contract; this file keeps the Plan 123 file-based load path
(`service.load('router_atomic_write', ...)`) working. Python 3.9-safe.
"""
import importlib.util as _ilu
from pathlib import Path

_spec = _ilu.spec_from_file_location(
    'router_runtime_atomic_write',
    Path(__file__).resolve().parents[1] / 'ai_router' / 'atomic_write.py')
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

replace_text = _mod.replace_text
replace_bytes = _mod.replace_bytes
replace_json = _mod.replace_json
StaleTmp = _mod.StaleTmp
ConcurrentChange = _mod.ConcurrentChange
check_unchanged = _mod.check_unchanged
remove = _mod.remove
