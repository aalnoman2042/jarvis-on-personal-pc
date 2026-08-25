"""FallbackBrain — wraps an AI brain and drops to the offline brain on failure.

If the AI brain (Groq/Gemini/Claude) is rate-limited, unreachable, or errors,
Jarvis instantly answers with the offline rule-based brain instead of failing.
That covers PC commands (open/close apps, time, volume, search, system info) with
no key and no limits, so Jarvis stays useful even when the internet or API is down.
"""
from __future__ import annotations

import time

# How long to stop asking a brain that just failed. Without this, every single
# question pays the cost of the dead brain timing out or refusing before moving
# on — which is what makes replies feel slow once a free tier runs out.
COOLDOWN_SECONDS = 300.0       # ordinary failure (network blip, bad response)
QUOTA_COOLDOWN_SECONDS = 1800.0  # "used up your free allowance" — back off longer


def _looks_like_quota(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(s in text for s in ("rate limit", "rate_limit", "429", "quota", "exhausted"))


class FallbackBrain:
    def __init__(self, primary, backup) -> None:
        self._primary = primary
        self._backup = backup
        self._skip_until = 0.0
        # e.g. "groq+ollama+gemini+free" — the whole chain, in the order tried.
        self.name = f"{primary.name}+{backup.name}"

    def greeting(self) -> str:
        return self._primary.greeting()

    def handle(self, text: str) -> str:
        now = time.monotonic()
        if now < self._skip_until:
            # Still cooling off — go straight to the backup, no waiting.
            return self._backup.handle(text)
        try:
            return self._primary.handle(text)
        except Exception as exc:  # noqa: BLE001  (any API/network failure)
            wait = QUOTA_COOLDOWN_SECONDS if _looks_like_quota(exc) else COOLDOWN_SECONDS
            self._skip_until = time.monotonic() + wait
            print(f"[{self._primary.name} unavailable ({exc}); "
                  f"using {self._backup.name} and skipping it for {wait / 60:.0f} min]")
            return self._backup.handle(text)


class LazyBrain:
    """Wraps a brain that is expensive to start, and doesn't start it until the
    first question actually reaches it.

    This is what keeps the local AI off your PC: the cloud brain answers
    everything, and the local model is only downloaded into RAM the first time
    the cloud brain fails. If it's never needed, it never runs.
    """

    def __init__(self, factory, name: str) -> None:
        self._factory = factory
        self._brain = None
        self.name = name

    def greeting(self) -> str:
        return self._brain.greeting() if self._brain else ""

    def handle(self, text: str) -> str:
        if self._brain is None:
            print(f"[waking the local {self.name} brain — first use this session]")
            self._brain = self._factory()
        return self._brain.handle(text)

    @property
    def started(self) -> bool:
        return self._brain is not None
