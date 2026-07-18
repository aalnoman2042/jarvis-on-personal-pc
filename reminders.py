"""Reminders / timers — a background service that speaks when a reminder is due.

Usage: vondo.py calls reminders.start(voice.say) once at launch. Then any brain
(or actions.set_reminder) calls reminders.add(delay_seconds, message). A daemon
thread checks every second and speaks reminders as they come due — even while
the assistant is otherwise idle and listening.
"""
from __future__ import annotations

import threading
import time

import config

_lock = threading.Lock()
_items: list[tuple[float, str]] = []  # (due_epoch, message)
_speak = None  # callback, set by start()
_started = False


def start(speak_callback) -> None:
    """Begin the background reminder loop, using speak_callback to announce them."""
    global _speak, _started
    _speak = speak_callback
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True).start()


def add(delay_seconds: float, message: str) -> None:
    """Schedule a reminder to be spoken after delay_seconds from now."""
    with _lock:
        _items.append((time.time() + max(0.0, delay_seconds), message))


def pending() -> int:
    with _lock:
        return len(_items)


def _loop() -> None:
    while True:
        now = time.time()
        due: list[tuple[float, str]] = []
        with _lock:
            keep = []
            for item in _items:
                (due if item[0] <= now else keep).append(item)
            _items[:] = keep
        for _, message in due:
            if _speak:
                title = f", {config.USER_TITLE}" if config.USER_TITLE else ""
                _speak(f"Reminder{title}: {message}")
        time.sleep(1)
