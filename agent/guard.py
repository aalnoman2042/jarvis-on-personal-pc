"""What the agent will and will not do when the cloud asks.

The agent is the only thing standing between a request arriving over the
internet and something happening to Rohan's actual machine. Two rules:

**An allow-list, not a block-list.** Only the functions the cloud legitimately
knows how to ask for can run. Anything else — a typo, a newer server, a
compromised one asking for `eval` — is refused by name before it is looked up.
A block-list would have to anticipate every dangerous thing; this has to
anticipate nothing.

**A second confirmation, on this machine, for what cannot be undone.** The cloud
already asks "say yes to confirm" before a shutdown, but that gate is code
running on a server. If the server were compromised, or a reply were misheard,
that gate is exactly as trustworthy as the thing that failed. So shutting down,
restarting, or force-killing an app also has to get past a dialog box on the
desk. It costs one click, and it means nothing irreversible happens to this PC
without something on this PC agreeing.

**Remote control is the exception the other two rules cannot cover, so it gets
its own.** A mouse and a keyboard are every action at once: an allow-list of
named functions means nothing when one of those functions is "click here", and
a per-action dialog would ask fifty times a minute. So permission is asked once
per run of this agent, for the whole capability, in the same box — and refusing
is remembered too, so a "no" cannot be worn down by asking again. Restarting
the agent is what re-opens the question.

Watching is not driving. `screen_frame` is read-only and no more revealing than
`take_screenshot`, which has never asked, so only input is gated.
"""
from __future__ import annotations

import ctypes
import threading

from core.lazy import PC_FUNCTIONS

# The allow-list is exactly the set of functions the cloud can route, defined
# once in core.lazy. Importing it rather than retyping it means the two can
# never drift into "the server can ask for something the agent forgot about".
ALLOWED = PC_FUNCTIONS

CONFIRM_SECONDS = 30

# Win32 MessageBox flags.
_MB_YESNO = 0x00000004
_MB_ICONWARNING = 0x00000030
_MB_DEFBUTTON2 = 0x00000100      # "No" is focused, so a stray Enter refuses
_MB_SYSTEMMODAL = 0x00001000     # sits above full-screen apps and games
_MB_TOPMOST = 0x00040000
_IDYES = 6

_dialog_lock = threading.Lock()

# Remote control, decided once per run of this agent. None means not yet asked.
# A refusal sticks: a gate that re-asks every thirty seconds is one that gets
# clicked through eventually, which is the opposite of a gate.
_remote_allowed: bool | None = None
_remote_lock = threading.Lock()


def remote_control_allowed() -> bool | None:
    """What was decided this run, or None if it has not come up yet."""
    return _remote_allowed


def _ask_about_remote_control() -> bool:
    global _remote_allowed
    with _remote_lock:
        if _remote_allowed is not None:
            return _remote_allowed
        _remote_allowed = _ask_on_screen(
            "Jarvis wants to CONTROL THIS PC from your phone.\n\n"
            "It will be able to click, type and drag exactly as you can, "
            "without asking again.\n\n"
            "Allow until this agent is restarted?"
        )
    return _remote_allowed


class Refused(Exception):
    """The agent declined. The message is meant to be spoken back to Rohan."""


def _needs_local_confirmation(tool: str, args: list, kwargs: dict) -> str:
    """Return a question to put on screen, or '' if this needs no dialog."""
    values = [str(v).strip().lower() for v in list(args) + list(kwargs.values())]
    first = values[0] if values else ""

    if tool == "power_control":
        if first in ("shutdown", "shut down"):
            return "Jarvis wants to SHUT DOWN this PC.\n\nAllow it?"
        if first in ("restart", "reboot"):
            return "Jarvis wants to RESTART this PC.\n\nAllow it?"
        return ""  # 'cancel' undoes a pending shutdown — never worth asking

    if tool == "close_app":
        # Closing the window in front is polite: it asks the app to close, so
        # anything unsaved still prompts you. Closing by name force-kills every
        # window that app owns and throws unsaved work away. Only the second
        # one is worth interrupting for.
        from core import actions
        if actions.is_front_window(first):
            return ""
        return (f"Jarvis wants to force close {first or 'an app'}.\n\n"
                "Anything unsaved there will be lost. Allow it?")

    return ""


def _ask_on_screen(question: str) -> bool:
    """Put a modal dialog on Rohan's screen. False if he says no or says nothing.

    MessageBoxTimeoutW is undocumented but has shipped in user32 for two decades.
    If it is ever missing we refuse rather than fall back to a dialog that could
    hang forever waiting for a machine nobody is sitting at.
    """
    user32 = ctypes.windll.user32
    if not hasattr(user32, "MessageBoxTimeoutW"):
        return False
    flags = (_MB_YESNO | _MB_ICONWARNING | _MB_DEFBUTTON2
             | _MB_SYSTEMMODAL | _MB_TOPMOST)
    # One dialog at a time: two stacked modal boxes is how a person clicks the
    # wrong one.
    with _dialog_lock:
        answer = user32.MessageBoxTimeoutW(
            None, question, "Jarvis needs your permission",
            flags, 0, int(CONFIRM_SECONDS * 1000),
        )
    return answer == _IDYES


def check(tool: str, args: list, kwargs: dict) -> None:
    """Raise Refused unless this call may go ahead."""
    if tool not in ALLOWED:
        raise Refused(f"This PC doesn't allow {tool!r}.")

    # Asked once for the whole capability rather than once per click. Handled
    # before the table below because it is a different shape of question: not
    # "is this action dangerous" but "is this phone allowed to be the mouse".
    if tool == "screen_input" and not _ask_about_remote_control():
        raise Refused(
            "Remote control isn't allowed on this PC. Say yes to the box on "
            "the desk, or restart the agent to be asked again.")

    question = _needs_local_confirmation(tool, args, kwargs)
    if not question:
        return
    if not _ask_on_screen(question):
        raise Refused(
            "I asked on your PC and didn't get a yes, so I've left it alone.")
