"""launchd domain helpers that converge instead of trusting a single rc.

`launchctl bootout` returns 0 as soon as teardown *starts*: the job stays in
`SIGTERMed` until the process actually exits, and the router drains in-flight
requests for up to its `ExitTimeOut`. A `bootstrap` issued inside that window
fails with `Bootstrap failed: 5: Input/output error`, so a naive
bootout-then-bootstrap pair reliably ends with no job loaded at all. That is
unrecoverable by design elsewhere in the installer: `launchctl kill TERM`
relies on `KeepAlive`, and an absent job has nothing to keep alive, so the
machine simply loses the router until someone bootstraps it by hand.

Every helper here waits for the domain to settle and verifies the end state.
`run` and `sleep` are injected so the installer's existing patchable seams
keep tests hermetic. Runs on Python 3.9+ like the rest of packaging.

Keep this module stateless: service.py and platforms/darwin.py each spec-load
their own copy (the linux.py/systemd.py pattern), so only constants and pure
functions belong here.
"""
import os
import plistlib
import time
from pathlib import Path

PROGRAM_PREFIX = 'program = '
ARGUMENTS_BLOCK = 'arguments = {'


def plist_path(label, agents=None):
    return Path(agents or (Path.home() / 'Library' / 'LaunchAgents')) / (label + '.plist')


def job_loaded(run, uid, label):
    """True when launchd knows the label in the user's gui domain."""
    return run(['launchctl', 'print', f'gui/{uid}/{label}'],
               capture_output=True).returncode == 0


def loaded_command(run, uid, label):
    """launchd's in-memory ProgramArguments, or None when not loaded.

    The on-disk plist is not the running configuration: rewriting a loaded
    plist leaves launchd's copy untouched until the job is reloaded, so this
    is the only honest answer to "what is actually scheduled right now".
    Comparing the whole command matters -- an update that changes only
    argv[1] (a per-release installer path to a stable launcher) is invisible
    to a check that reads the interpreter alone.
    """
    out = run(['launchctl', 'print', f'gui/{uid}/{label}'],
              capture_output=True, text=True)
    if out.returncode != 0:
        return None
    lines = (out.stdout or '').splitlines()
    for index, line in enumerate(lines):
        if line.strip() == ARGUMENTS_BLOCK:
            argv = []
            for raw in lines[index + 1:]:
                token = raw.strip()
                if token == '}':
                    return argv or None
                argv.append(token)
            return None
    # A job launchd started from a bare program reports no arguments block.
    for line in lines:
        token = line.strip()
        if token.startswith(PROGRAM_PREFIX):
            program = token[len(PROGRAM_PREFIX):].strip()
            return [program] if program else None
    return None


def unload(run, uid, label, timeout=180, sleep=time.sleep, poll=0.5):
    """bootout, then wait for the label to leave the domain. True once gone.

    bootout's own exit code is ignored on purpose: it reports success for
    "teardown started" and failure for "was not loaded", and a caller that
    only needs the label absent treats those the same.
    """
    run(['launchctl', 'bootout', f'gui/{uid}/{label}'], capture_output=True)
    deadline = time.monotonic() + timeout
    while True:
        if not job_loaded(run, uid, label):
            return True
        if time.monotonic() >= deadline:
            return False
        sleep(poll)


def load(run, uid, label, agents=None, timeout=60, sleep=time.sleep, poll=1):
    """bootstrap until the label is really loaded. True on success.

    A no-op when the label is already there, so this is also the
    ensure-it-is-loaded call. Retried rather than trusted once: a bootstrap
    racing a still-draining predecessor returns error 5, and the only
    reliable success signal is the label appearing in the domain.
    """
    path = str(plist_path(label, agents))
    deadline = time.monotonic() + timeout
    while True:
        if job_loaded(run, uid, label):
            return True
        run(['launchctl', 'bootstrap', f'gui/{uid}', path], capture_output=True)
        if job_loaded(run, uid, label):
            return True
        if time.monotonic() >= deadline:
            return False
        sleep(poll)


def reload_job(run, uid, label, agents=None, unload_timeout=180,
               load_timeout=60, sleep=time.sleep):
    """Unload and reload, waiting for each step. True when loaded again.

    The only safe way to make launchd adopt a rewritten plist. Fails closed
    when the old job refuses to leave, so a surviving stale job is never
    mistaken for a successful reload.
    """
    if not unload(run, uid, label, timeout=unload_timeout, sleep=sleep):
        return False
    return load(run, uid, label, agents=agents, timeout=load_timeout, sleep=sleep)


# --- Plist rendering and reload convergence (Plan 103) -----------------------
# Moved verbatim from packaging/service.py, which keeps thin delegations for
# the names packaging/install.py binds. This module stays a leaf: callers
# inject `run` and `sleep`, and labels live here so both callers agree.

LABEL = 'com.local.codex-mixed-model-router'
UPDATE_LABEL = LABEL + '.update'
EXPRESS_LABEL = UPDATE_LABEL + '.express'


def _agent_dir(agents=None):
    """LaunchAgents directory for the user agent plists."""
    return Path(agents) if agents else Path.home() / 'Library' / 'LaunchAgents'


def _require_absolute(python):
    # launchd never sees a shell PATH: persist the validated interpreter
    # identity, never a discovery token.
    if not python or not os.path.isabs(python):
        raise SystemExit(f'refusing non-absolute interpreter: {python!r}')
    return python


def render_plist(python, home, state):
    python = _require_absolute(python)
    return {'Label': LABEL,
            'ProgramArguments': [python, str(home / 'router_launch.py')],
            'Sockets': {'Listeners': {'SockNodeName': '127.0.0.1',
                                      'SockServiceName': str(state['port']),
                                      'SockFamily': 'IPv4',
                                      'SockType': 'stream'}},
            # No WorkingDirectory: the router resolves everything from
            # ROUTER_HOME and its own file location, so the plist stays valid
            # across releases and a plain TERM restarts into the new pointer.
            # ExitTimeOut covers the router drain deadline so launchd stops wait
            # instead of SIGKILLing mid-drain on bootout/uninstall.
            'EnvironmentVariables': {'ROUTER_HOME': str(home)},
            'KeepAlive': True, 'RunAtLoad': True, 'ThrottleInterval': 10, 'Umask': 63,
            'ExitTimeOut': 150,
            'StandardOutPath': str(home / 'logs' / 'launchd.log'),
            'StandardErrorPath': str(home / 'logs' / 'launchd.log')}


def render_update_plist(python, home, express=False):
    python = _require_absolute(python)
    # The stable home launcher, never a per-release install.py path. launchd
    # keeps running its in-memory copy of a loaded plist, so a versioned path
    # outlives the release it names: after a prune the updater keeps firing a
    # deleted or obsolete installer every 4 hours. update_launch.py
    # resolves `current` at exec time instead, exactly like router_launch.py.
    args = [python, str(home / ('express_launch.py' if express else 'update_launch.py'))]
    return {'Label': EXPRESS_LABEL if express else UPDATE_LABEL,
            'ProgramArguments': args,
            'RunAtLoad': True,
            'StartInterval': 60 if express else 14400,
            'StandardOutPath': str(home / 'logs' / 'update.log'),
            'StandardErrorPath': str(home / 'logs' / 'update.log')}


def write_plist(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as stream:
        plistlib.dump(content, stream)


def restart_service(run, uid, agents=None, *, sleep,
                    unload_timeout, load_timeout):
    # First install: a reload rather than a plain load, because "no previous
    # release" does not prove no job is loaded -- a half-finished earlier
    # attempt can leave one behind running a release that is now gone.
    agents = _agent_dir(agents)
    if not reload_job(run, uid, LABEL, agents=agents,
                               unload_timeout=unload_timeout,
                               load_timeout=load_timeout, sleep=sleep):
        raise SystemExit(f'bootstrap failed for {LABEL}')
    if not load(run, uid, UPDATE_LABEL, agents=agents,
                         timeout=load_timeout, sleep=sleep):
        raise SystemExit(f'bootstrap failed for {UPDATE_LABEL}')


def same_interpreter(left, right):
    """True when two paths name the same interpreter binary.

    `/opt/homebrew/bin/python3.14` and
    `/opt/homebrew/opt/python@3.14/bin/python3.14` are one binary reached by
    two symlink spellings. A string compare calls them different and forces
    the destructive reload path on a run that only needed a TERM handover.
    """
    if not left or not right:
        return False
    try:
        return os.path.realpath(left) == os.path.realpath(right)
    except OSError:
        return left == right


def command_matches(loaded, rendered):
    """True when launchd's loaded command is the one we intend to run.

    argv[0] is compared by resolved path because two symlink spellings name
    one interpreter; every later argument must match exactly, so a changed
    launcher path is never mistaken for no change at all.
    """
    if not loaded or not rendered or len(loaded) != len(rendered):
        return False
    if not same_interpreter(loaded[0], rendered[0]):
        return False
    return list(loaded[1:]) == list(rendered[1:])


def running_under(label):
    """True when this process is inside the launchd job for `label`.

    launchd stamps XPC_SERVICE_NAME into the job's environment and children
    inherit it, so the scheduled updater's own installer can tell that
    booting out that label would kill the process issuing the bootout.
    """
    return os.environ.get('XPC_SERVICE_NAME') == label


def plist_differs(path, content):
    """True when the plist on disk does not already say exactly this."""
    try:
        return plistlib.loads(Path(path).read_bytes()) != content
    except (OSError, ValueError):
        return True


def main_plist_needs_reload(run, uid, python, home, state, agents=None):
    """True when launchd is running something other than what we will write.

    Compared against launchd's in-memory program rather than the file: a
    previous failed run may already have rewritten the plist while the loaded
    job kept the old command.
    """
    agents = _agent_dir(agents)
    rendered = render_plist(python, home, state)
    loaded = loaded_command(run, uid, LABEL)
    if loaded is None or not command_matches(loaded, rendered['ProgramArguments']):
        return True
    # Catches everything launchd owns that is not argv, the port above all.
    return plist_differs(agents / (LABEL + '.plist'), rendered)


def ensure_updater(run, uid, python, home, agents=None, *, sleep,
                   unload_timeout, load_timeout, express=False):
    """Keep the scheduled updater loaded and running the current command.

    Writing the file is not enough: launchd adopts a rewritten plist only on
    reload, which is how the updater kept invoking an installer from a release
    that had already been pruned.

    But the scheduled updater is what runs this installer, so a bootout here
    would kill the process issuing it and leave the job unloaded with no
    bootstrap -- the same silent-loss failure this release fixes for the
    router. When this run *is* that job, the rewritten file is left for the
    next manual install or login to adopt; the plist now names a
    release-independent launcher, so one adoption is final.
    """
    agents = _agent_dir(agents)
    label = EXPRESS_LABEL if express else UPDATE_LABEL
    rendered = render_update_plist(python, home, express)['ProgramArguments']
    loaded = loaded_command(run, uid, label)
    if loaded is None:
        return load(run, uid, label, agents=agents,
                             timeout=load_timeout, sleep=sleep)
    if command_matches(loaded, rendered):
        return True
    if running_under(label):
        print('scheduled updater command changed; adopting it needs a reload '
              'from outside its own job, so the next manual install or login '
              'will pick it up')
        return True
    return reload_job(run, uid, label, agents=agents,
                               unload_timeout=unload_timeout,
                               load_timeout=load_timeout, sleep=sleep)


def loaded_updater_release(run, uid, home):
    """Release name inside launchd's loaded updater command, or None.

    Before this release the updater plist named a per-release installer, and
    launchd runs the command it loaded until the job is reloaded -- which a
    scheduled run deliberately defers, because it cannot bootout its own job.
    Pruning that release would leave the updater firing a missing file.
    """
    prefix = str(Path(home) / 'releases') + os.sep
    for token in (loaded_command(run, uid, UPDATE_LABEL) or [])[1:]:
        if token.startswith(prefix):
            return token[len(prefix):].split(os.sep)[0] or None
    return None


def reload_main_service(run, uid, agents=None, *, sleep,
                       unload_timeout, load_timeout):
    """Make launchd adopt the rewritten main plist. True when loaded again.

    Rewriting a loaded plist does not update launchd's in-memory copy; only a
    reload picks up a changed interpreter or port. The updater is never
    touched here. Returns False rather than raising so the caller can roll
    back and then restore service on the previous release.
    """
    return reload_job(run, uid, LABEL, agents=_agent_dir(agents),
                               unload_timeout=unload_timeout,
                               load_timeout=load_timeout, sleep=sleep)
