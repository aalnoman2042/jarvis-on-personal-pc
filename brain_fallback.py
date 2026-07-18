"""FallbackBrain — wraps an AI brain and drops to the offline brain on failure.

If the AI brain (Groq/Gemini/Claude) is rate-limited, unreachable, or errors,
Jarvis instantly answers with the offline rule-based brain instead of failing.
That covers PC commands (open/close apps, time, volume, search, system info) with
no key and no limits, so Jarvis stays useful even when the internet or API is down.
"""
from __future__ import annotations


class FallbackBrain:
    def __init__(self, primary, backup) -> None:
        self._primary = primary
        self._backup = backup
        self.name = f"{primary.name}+offline"

    def greeting(self) -> str:
        return self._primary.greeting()

    def handle(self, text: str) -> str:
        try:
            return self._primary.handle(text)
        except Exception as exc:  # noqa: BLE001  (any API/network failure)
            print(f"[{self._primary.name} brain unavailable ({exc}); using offline brain]")
            return self._backup.handle(text)
