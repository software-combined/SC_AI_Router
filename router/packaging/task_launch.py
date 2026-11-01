"""Windows task entry point, written by the installer. Not imported.

Routes the task's stdout/stderr to the supervisor log under logs/, then
runs the stable home launcher (router_launch.py or update_launch.py).
"""
import os
import json
import runpy
import sys
from datetime import datetime, timezone

task = {'router_launch.py': 'router', 'update_launch.py': 'regular',
        'express_launch.py': 'express'}.get(sys.argv[2] if len(sys.argv) > 2 else '', 'unknown')


def event(name, status=None, error=None):
    row = dict(at=datetime.now(timezone.utc).isoformat(), task=task, event=name)
    if status is not None:
        row['status'] = status
    if error:
        row['error'] = error
    print(json.dumps(row), flush=True)


home = os.path.dirname(os.path.abspath(__file__))
if len(sys.argv) != 3:
    event('launch')
    event('failed', 1, 'invalid_arguments')
    raise SystemExit('task launcher needs LOG and SCRIPT arguments')
log, script = sys.argv[1], sys.argv[2]
logs = os.path.join(home, 'logs')
path = os.path.join(logs, log)
try:
    if os.path.getsize(path) > 1048576:
        os.replace(path, path + '.1')
except OSError:
    pass  # rotation is hygiene; a held-open log must not stop the launch
try:
    os.makedirs(logs, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
except OSError:
    event('launch')
    event('failed', 1, 'log_unavailable')
    raise SystemExit(1)
os.dup2(fd, 1)
os.dup2(fd, 2)
if fd not in (1, 2):
    os.close(fd)
sys.stdout = open(1, 'w', 1, 'utf-8', 'replace')
sys.stderr = open(2, 'w', 1, 'utf-8', 'replace')
sys.argv = [os.path.join(home, script), '--home=' + home]
event('launch')
if not os.path.isfile(sys.argv[0]):
    event('failed', 1, 'missing_target')
    raise SystemExit(1)
try:
    runpy.run_path(sys.argv[0], run_name='__main__')
except SystemExit as exc:
    code = 0 if exc.code is None else exc.code if isinstance(exc.code, int) else 1
    event('completed' if code == 0 else 'failed', code, 'target_exit' if code else None)
    raise
except Exception:
    event('failed', 1, 'target_failed')
    raise SystemExit(1) from None
else:
    event('completed', 0)
