"""Building a brain, in one place.

The desktop app and the cloud server must construct brains identically — same
chain, same failover, same memory wrapping — or the two grow apart and "it works
on my PC but not from my phone" becomes a class of bug rather than an incident.
This module is that single definition; `legacy/vondo.py` and `server/` both come
through here.

Brains are imported lazily inside each branch, never at module level: pulling in
every brain would drag in every provider SDK, and one missing optional package
would break the whole core.
"""
from __future__ import annotations

from core import config
from core import confirm
from core import memory


def make(choice: str | None = None):
    """Build a brain that remembers the conversation and falls back gracefully.

    Pass `choice` to build a specific brain (the UI dropdown does this when you
    switch); leave it out to use whatever VONDO_BRAIN says in .env.
    """
    # Wrapping the whole chain means every exchange is recorded once, whichever
    # brain in it answered — which is what lets a later brain carry on a
    # conversation an earlier one started.
    #
    # confirm sits inside memory: a "yes" answering "shut down the PC?" still
    # gets remembered as a normal exchange, but the model never sees the bare
    # "yes" — it has no idea an action was parked, and would only guess.
    return memory.wrap(confirm.wrap(build(choice)))


def build(choice: str | None = None):
    """Build the brain itself, wrapped so it auto-drops to the offline brain if
    the AI service is ever rate-limited or unreachable."""
    from core.brains.brain_free import FreeBrain
    from core.brains.brain_fallback import FallbackBrain, LazyBrain

    def _lazy_ollama():
        """The local model, wrapped so it only starts if it's actually reached."""
        from core.brains.brain_ollama import OllamaBrain
        return LazyBrain(OllamaBrain, "ollama")

    choice = (choice or config.BRAIN).strip().lower()

    # Every AI brain that could answer, in the order they are worth trying.
    # Named separately from the chain-builder so "which brains exist" and "which
    # order" stay one decision each.
    def _groq():
        from core.brains.brain_groq import GroqBrain
        return GroqBrain()

    def _gemini():
        from core.brains.brain_gemini import GeminiBrain
        return GeminiBrain()

    def _claude():
        from core.brains.brain_claude import ClaudeBrain
        return ClaudeBrain()

    def _ollama():
        from core.brains.brain_ollama import OllamaBrain
        return OllamaBrain()

    # Groq first: fastest and free. Gemini second: free, and the only one that
    # sees images. Claude only when explicitly chosen — it is the paid one.
    PREFERRED = (("groq", _groq), ("gemini", _gemini))

    def _chain(first: str | None) -> object:
        """Every brain that will start, tried in turn, ending offline.

        The point of the whole arrangement: if one is rate-limited, down, or
        has had its model retired from under it, the next one answers and Rohan
        never sees a failure. The offline brain is last because it always works
        and is always the worst of them.

        Built by *trying* each brain rather than by asking whether a key is set.
        A key that is present but wrong, a package that is missing, a model that
        was withdrawn — all of those look fine to a config check and fail at the
        first question.
        """
        from core.brains.brain_free import FreeBrain

        wanted: list[tuple[str, object]] = []
        extra = {"claude": _claude, "ollama": _ollama}
        if first and first in extra:
            wanted.append((first, extra[first]))
        for name, maker in PREFERRED:
            if name == first:
                wanted.insert(0, (name, maker))
            else:
                wanted.append((name, maker))

        built = []
        for name, maker in wanted:
            try:
                built.append(maker())
            except Exception as exc:  # noqa: BLE001  (no key, no package, bad model)
                print(f"[{name} not available: {exc}]")

        # Assembled from the back so the offline brain is everyone's last
        # resort rather than only the last one's.
        brain = FreeBrain()
        for candidate in reversed(built):
            brain = FallbackBrain(candidate, brain)
        return brain

    try:
        if choice in ("auto", "groq", "gemini", "claude", "ollama"):
            # A named brain goes FIRST — it does not go ALONE. Choosing "groq"
            # used to build groq+free and silently drop Gemini, so a Groq outage
            # fell straight past a perfectly good second brain to the rule-based
            # one, which answers but cannot think. That looked like Jarvis
            # having a bad day rather than a chain with a hole in it.
            return _chain(None if choice == "auto" else choice)
        if choice == "free":
            return FreeBrain()
        print(f"[unknown VONDO_BRAIN '{choice}', using the full chain]")
        return _chain(None)
    except ImportError as exc:
        print(f"[missing package for '{choice}' brain: {exc}. "
              f"Run: pip install -r requirements/cloud.txt]")
    except Exception as exc:  # noqa: BLE001  (e.g. missing API key)
        print(f"[couldn't start '{choice}' brain: {exc}]")
    print("[falling back to the offline rule-based brain]")
    from core.brains.brain_free import FreeBrain
    return FreeBrain()
