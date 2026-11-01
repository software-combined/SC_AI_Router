"""Explicit restart through the service owner, after the installer takes its lock."""
import json
import sys
from pathlib import Path


def restart(args, service, backend):
    home = Path(args.home).expanduser()
    if args.dry_run:
        print('would restart SCG Router')
        return 0
    release = service.current_release_dir(home)
    if release is None:
        raise SystemExit('SCG Router needs setup before it can restart.')
    state = json.loads((home / 'mixed-router-state.json').read_text())
    python = service.find_python(args.python or sys.executable)
    if not python:
        raise SystemExit('SCG Router needs repair before it can restart.')
    # The repair lifecycle waits for the old process to leave. Same-version
    # health after TERM alone could accept the process that is still draining.
    backend.install(python, home, state, release, None)
    if not service.wait_version(state, service.current_version(home)):
        raise SystemExit('SCG Router did not restart. Choose Update or repair.')
    print('SCG Router restarted')
    return 0
