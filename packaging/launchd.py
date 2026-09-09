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
"""
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
