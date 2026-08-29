"""Where Jarvis's hands are — and how the cloud borrows them.

Two jobs, both about `core.actions`, which is the one module in `core` that
genuinely needs Rohan's desktop:

**1. Deferred import.** `core.actions` pulls in pyautogui and ctypes. Fine on
Windows, fatal on a headless Linux box, and the cloud core has to import cleanly
there. Every call site does its work inside a function body, so the import
statement is the only eager part. This defers exactly that.

**2. Routing.** On the desktop these functions run right here. In the cloud there
is no desktop, so the server installs `pc_handler` and the OS-touching functions
are forwarded down the websocket to the PC agent instead.

Routing lives at *this* layer rather than in the tool dispatcher because the
brains do not agree on how they reach the PC. Groq, Ollama and Claude go through
`llm_tools.DISPATCH`; the rule-based FreeBrain calls `actions.open_app` directly.
Hooking the dispatcher alone would have covered the AI brains and quietly missed
the offline one — which is the brain most likely to be answering when everything
else has failed. One hook, under all of them, cannot be bypassed that way.
"""
from __future__ import annotations

import functools
import importlib
import threading
from types import ModuleType

# Functions in core.actions that do something to the physical machine. Anything
# not listed here — web_answer, read_webpage, get_time, set_reminder — is
# perfectly happy in the cloud and keeps working with the PC switched off.
#
# is_front_window is deliberately absent: it only compares a string against a
# list of phrases meaning "this window", and llm_tools branches on its result.
# Routing it would send a bool question over the network and get a sentence back.
PC_FUNCTIONS = frozenset({
    "open_app", "close_app", "close_active_window", "active_window",
    "top_processes", "open_website", "web_search", "write_code",
    "take_screenshot", "lock_screen", "control_volume", "media_control",
    "power_control", "set_autostart", "system_info",
    "set_power_state", "power_state_on", "autostart_enabled",
    # Remote control. `screen_frame` is read-only and behaves like the
    # screenshot beside it; `screen_input` is the one entry point for every
    # click, scroll and keystroke, which is what gives the agent a single place
    # to ask permission for the whole capability rather than eight.
    "screen_frame", "screen_size", "screen_input",
})

# Set by server.agents.install_hook. Signature: (name, kwargs) -> str.
pc_handler = None

# Not written to the action log, and the first three are the reason this list
# exists. The remote viewer pulls frames continuously, so logging them would
# write several rows a second to a database on the far side of an HTTPS
# connection, and would bury every real action under thousands of "screen
# frame" lines — destroying the panel the log exists for. The last two are
# readings rather than actions: nothing happened, so there is nothing to record.
NOT_WORTH_LOGGING = frozenset({
    "screen_frame", "screen_size", "screen_input",
    "active_window", "system_info", "is_front_window", "power_state_on",
    "autostart_enabled", "top_processes",
})


def _log_calls(name: str, fn):
    """Record a desktop action that never went through the tool dispatcher.

    `llm_tools._logged` wraps DISPATCH, which covers Groq and Ollama only.
    Gemini calls the plain callables, Claude declares its own tools, and the
    offline brain calls `actions.*` directly — so three brains of five left no
    trace of what they did, and the HUD's "Recently done" panel drew "did three
    things, logged none" and "did nothing" identically. This sits underneath
    all of them and cannot be bypassed, which is the same reason PC routing
    lives here rather than in the dispatcher.

    It is also what turns the log into training data: each row carries the
    sentence that caused it, so "what he asked" and "what should happen" are a
    labelled pair rather than two things to correlate by timestamp.
    """
    if name in NOT_WORTH_LOGGING:
        return fn

    @functools.wraps(fn)
    def call(*args, **kwargs):
        detail = ", ".join([str(a) for a in args]
                           + [f"{k}={v}" for k, v in kwargs.items()])
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            _record(name, detail, f"{type(exc).__name__}: {exc}", False)
            raise
        _record(name, detail, str(result), True)
        return result

    return call


# Set while the tool dispatcher is already recording this call. Without it a
# Groq tool that reaches the desktop is logged twice — once by
# `llm_tools._logged` on the way in and once here on the way down — and the
# panel shows every PC action in duplicate. Thread-local because the agent
# answers several calls at once and a plain flag would leak between them.
_dispatching = threading.local()


class already_logged:  # noqa: N801  (a context manager reads better lowercase)
    """Used by the tool dispatcher to say "this one is mine"."""

    def __enter__(self):
        _dispatching.on = True
        return self

    def __exit__(self, *_exc):
        _dispatching.on = False
        return False


def _record(name: str, detail: str, result: str, ok: bool) -> None:
    """One row. Never raises — a logging failure must not lose the action."""
    if getattr(_dispatching, "on", False):
        return
    try:
        from core import memory
        memory.log_action(name, detail, result, ok=ok, said=memory.now_asking())
    except Exception:  # noqa: BLE001
        pass


class LazyModule:
    """Stands in for a module, importing it on first attribute access.

    Call sites read exactly as they always did (`actions.open_app(...)`), so
    neither lazy loading nor remote execution needed a single one to change.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._module: ModuleType | None = None

    def _load(self) -> ModuleType:
        if self._module is None:
            self._module = importlib.import_module(self._name)
        return self._module

    def __getattr__(self, attr: str):
        # Only reached for names not already on the instance, so _name and
        # _module never recurse through here.
        if pc_handler is not None and attr in PC_FUNCTIONS:
            return _log_calls(attr, _remote(attr))
        found = getattr(self._load(), attr)
        if callable(found) and not attr.startswith("_"):
            return _log_calls(attr, found)
        return found

    def __dir__(self):
        return dir(self._load())

    def __repr__(self) -> str:
        where = "remote" if pc_handler is not None else (
            "loaded" if self._module is not None else "not loaded yet")
        return f"<lazy module {self._name!r} ({where})>"


def _remote(name: str):
    """A stand-in that sends the call to the PC agent instead of running it."""
    def call(*args, **kwargs) -> str:
        handler = pc_handler
        if handler is None:  # unhooked between the check and the call
            return getattr(actions._load(), name)(*args, **kwargs)
        return handler(name, list(args), dict(kwargs))
    call.__name__ = name
    call.__qualname__ = f"remote.{name}"
    return call


actions = LazyModule("core.actions")
