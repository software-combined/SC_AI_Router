"""Inherit the launchd listening socket when socket-activated."""
import ctypes
import threading
from .events import log_event

# launch_activate_socket is synchronous launchd IPC (ctypes releases the GIL):
# instant when healthy, but it never returns in some hosted macOS contexts,
# wedging boot with no listener and no error. Bound the wait so boot falls
# back to the configured bind.
ACTIVATION_WAIT_S = 5


def _activate(box):
    try:
        fds = ctypes.POINTER(ctypes.c_int)()
        count = ctypes.c_size_t(0)
        rc = ctypes.CDLL(None).launch_activate_socket(
            b'Listeners', ctypes.byref(fds), ctypes.byref(count))
        if rc == 0 and count.value >= 1:
            box.append(fds[0])
    except Exception:
        pass


def inherited_listener():
    """Return the launchd-provided listener fd, or None. Never raises."""
    try:
        box = []
        worker = threading.Thread(target=_activate, args=(box,), daemon=True)
        worker.start()
        worker.join(timeout=ACTIVATION_WAIT_S)
        if box:
            log_event('socket_activation', inherited=True)
            return box[0]
        # A live worker means slow-not-absent IPC: the fallback bind may
        # orphan a genuine launchd queue, so say timed-out, not absent.
        timed_out = worker.is_alive()
    except Exception:
        timed_out = False
    log_event('socket_activation', inherited=False, timed_out=timed_out)
    return None
