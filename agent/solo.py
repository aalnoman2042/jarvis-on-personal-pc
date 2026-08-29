"""Exactly one agent per machine, enforced rather than hoped for.

Two copies of the agent is not a rare accident. `start_agent.bat` gets
double-clicked, a Startup entry runs one while a window already has another, a
crash leaves an orphan — and the result is genuinely hard to diagnose, because
BOTH connections are healthy. They share one token, so they share one device id,
and each one's arrival displaces the other in the cloud's registry. The PC then
reads as reconnecting every few seconds while nothing is actually wrong with the
network, the server, or either agent. It cost an evening.

The cloud now closes the loser (see `Registry.add`), which stops the fight from
the far end. This stops it from *this* end, which is better: the second copy
never connects at all, and says why.

A named mutex rather than a PID file. A PID file has to answer "is that process
still alive, and is it actually mine?", and gets it wrong after a hard kill —
leaving a stale file that locks you out of your own machine until you find and
delete it. The kernel releases a mutex when the holder dies, whatever way it
died, and there is nothing left behind to clean up.
"""
from __future__ import annotations

import sys

# Global, so it also catches a copy started from another folder or another
# drive letter. Two agents in two checkouts is still two agents.
_NAME = "Global\\VONDO_PC_AGENT_SINGLE_INSTANCE"

_ERROR_ALREADY_EXISTS = 183
_handle = None


def claim() -> bool:
    """True if this process is now the only agent. False if one already runs.

    Never raises. On anything that is not Windows — or if the call is somehow
    unavailable — this returns True and lets the agent start: refusing to run
    because a lock could not be taken would turn a safety net into an outage.
    """
    global _handle
    if not sys.platform.startswith("win"):
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # The handle is kept on the module for the life of the process. Dropped,
        # it would be garbage collected, the mutex released, and the guard would
        # silently stop guarding.
        handle = kernel32.CreateMutexW(None, False, _NAME)
        if not handle:
            return True
        if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            # Somebody else owns it. Close OUR handle rather than keeping it:
            # every open handle counts, so hanging on to one we do not own
            # keeps the mutex alive after the real owner exits — and a refused
            # agent would then lock out the next one for ever.
            kernel32.CloseHandle(handle)
            return False
        _handle = handle
        return True
    except Exception:  # noqa: BLE001
        return True


def release() -> None:
    """Only needed by tests; the OS does this when the process ends."""
    global _handle
    if _handle:
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(_handle)
        except Exception:  # noqa: BLE001
            pass
        _handle = None
