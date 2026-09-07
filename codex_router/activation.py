"""Inherit the launchd listening socket when socket-activated."""
import ctypes
from .runtime import log_event


def inherited_listener():
    """Return the launchd-provided listener fd, or None. Never raises."""
    try:
        fds = ctypes.POINTER(ctypes.c_int)()
        count = ctypes.c_size_t(0)
        rc = ctypes.CDLL(None).launch_activate_socket(
            b'Listeners', ctypes.byref(fds), ctypes.byref(count))
        if rc == 0 and count.value >= 1:
            log_event('socket_activation', inherited=True)
            return fds[0]
    except Exception:
        pass
    log_event('socket_activation', inherited=False)
    return None
