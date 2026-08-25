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

import importlib
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
})

# Set by server.agents.install_hook. Signature: (name, kwargs) -> str.
pc_handler = None


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
            return _remote(attr)
        return getattr(self._load(), attr)

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
