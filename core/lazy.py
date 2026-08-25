"""Deferred imports for modules that are not safe to load everywhere.

`core.actions` pulls in pyautogui, psutil and ctypes — fine on Rohan's desktop,
but the cloud core has no screen and no Windows, and importing it there would
fail at startup. Every call site does its work inside a function body, so the
import is the only eager part. This defers exactly that.

Phase 03 removes the need for this by moving the Windows half of actions.py into
the PC agent; until then, this keeps `core` importable on Linux.
"""
from __future__ import annotations

import importlib
from types import ModuleType


class LazyModule:
    """Stands in for a module, importing it on first attribute access.

    Call sites read exactly as they did before (`actions.open_app(...)`), so the
    switch to lazy loading needed no changes anywhere else.
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
        return getattr(self._load(), attr)

    def __dir__(self):
        return dir(self._load())

    def __repr__(self) -> str:
        state = "loaded" if self._module is not None else "not loaded yet"
        return f"<lazy module {self._name!r} ({state})>"


actions = LazyModule("core.actions")
