"""Windows task entry point, written by the installer. Not imported.

Routes the task's stdout/stderr to the supervisor log under logs/, then
runs the stable home launcher (router_launch.py or update_launch.py).
"""
import os
import runpy
import sys

home = os.path.dirname(os.path.abspath(__file__))
if len(sys.argv) != 3:
    raise SystemExit('task launcher needs LOG and SCRIPT arguments')
log, script = sys.argv[1], sys.argv[2]
logs = os.path.join(home, 'logs')
os.makedirs(logs, exist_ok=True)
path = os.path.join(logs, log)
try:
    if os.path.getsize(path) > 1048576:
        os.replace(path, path + '.1')
except OSError:
    pass  # rotation is hygiene; a held-open log must not stop the launch
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
os.dup2(fd, 1)
os.dup2(fd, 2)
os.close(fd)
sys.stdout = open(1, 'w', 1, 'utf-8', 'replace')
sys.stderr = open(2, 'w', 1, 'utf-8', 'replace')
sys.argv = [os.path.join(home, script), '--home=' + home]
runpy.run_path(sys.argv[0], run_name='__main__')
