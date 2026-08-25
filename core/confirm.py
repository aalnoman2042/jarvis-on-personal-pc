"""A moment's pause before anything you can't undo.

Jarvis listens continuously and, on a phone-as-mic, mishears a fair amount. Most
of what it can do is harmless if triggered by accident — opening an app or
reading the time out is a shrug. Shutting the PC down is not, and neither is
force-killing an app with unsaved work in it.

So the dangerous few ask first. The tool doesn't run; it parks the action here
and answers with a question. If the very next thing you say is "yes", it runs.
Anything else cancels it and is treated as a normal request, so a misheard
"shut down" costs you one confused question rather than your session.

Everything else stays instant. A confirmation on "what time is it" would just
train you to say yes to everything, which is worse than not asking at all.
"""
from __future__ import annotations

import threading
import time

# How long a parked action stays offered. Say "yes" to something else five
# minutes later and it must not fire the shutdown you'd already forgotten about.
TIMEOUT_SECONDS = 45.0

_lock = threading.Lock()
_pending: dict | None = None
_raised = 0  # bumped whenever a question is parked, so a turn can notice

_YES = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed",
    "do it", "go ahead", "affirmative", "please do", "yes please", "correct",
}
_NO = {
    "no", "nope", "cancel", "stop", "don't", "dont", "never mind", "nevermind",
    "forget it", "abort", "negative",
}


def _fresh() -> dict | None:
    """The parked action, if there is one and it hasn't gone stale."""
    global _pending
    if _pending and time.monotonic() - _pending["at"] > TIMEOUT_SECONDS:
        _pending = None
    return _pending


def request(question: str, run) -> str:
    """Park an action and ask first. Returns the question to say out loud."""
    global _pending, _raised
    with _lock:
        _pending = {"question": question, "run": run, "at": time.monotonic()}
        _raised += 1
    return question


def pending() -> bool:
    with _lock:
        return _fresh() is not None


def cancel() -> None:
    global _pending
    with _lock:
        _pending = None


def _looks_like(text: str, words: set[str]) -> bool:
    """Is this short reply one of these words? Length matters — "yes" is an
    answer, "yes, and also open chrome" is a new request that happens to
    start with one."""
    cleaned = text.strip().strip(".!,").lower()
    return cleaned in words or (len(cleaned.split()) <= 3
                                and any(cleaned.startswith(w + " ") for w in words))


def resolve(text: str) -> str | None:
    """Handle a reply to a pending question.

    Returns what to say back, or None if this wasn't an answer to it — in which
    case the parked action is dropped and the words are treated as a fresh
    request. Silence on the question is the safe outcome, not the dangerous one.
    """
    global _pending
    with _lock:
        parked = _fresh()
        if not parked:
            return None
        if _looks_like(text, _YES):
            _pending = None
            run = parked["run"]
        elif _looks_like(text, _NO):
            _pending = None
            return "Cancelled."
        else:
            # Not an answer — assume the question was misheard or ignored, and
            # let this be a new request instead. Never carry the action over.
            _pending = None
            return None
    return run()  # run outside the lock: it can take a while


class ConfirmingBrain:
    """Wraps a brain so a "yes" answers the question Jarvis just asked.

    Sits between memory and the brains: the exchange still gets remembered, but
    the model never sees the bare "yes" — it has no idea an action was parked,
    and a small model asked to interpret one would happily invent something.
    """

    def __init__(self, brain) -> None:
        self._brain = brain
        self.name = getattr(brain, "name", "brain")

    def greeting(self) -> str:
        return self._brain.greeting()

    def handle(self, text: str) -> str:
        if text.strip() and pending():
            answer = resolve(text)
            if answer is not None:
                return answer

        with _lock:
            before = _raised
        reply = self._brain.handle(text)

        # If a question got parked while answering, say that question and
        # nothing else. Models paraphrase tool results, and a small one asked to
        # relay "say yes to confirm" has been seen to answer "I can't do that"
        # instead — while the action sat armed and the next "yes" fired it. What
        # the user hears has to match what is actually about to happen.
        with _lock:
            parked = _fresh()
            if _raised > before and parked:
                return parked["question"]
        return reply


def wrap(brain):
    return ConfirmingBrain(brain)
