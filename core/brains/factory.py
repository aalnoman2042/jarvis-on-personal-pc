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
    try:
        if choice == "auto":
            # Groq first: fastest, and nothing runs on the PC while it lasts.
            # Gemini after that, and the rule-based brain as a last resort.
            # A brain that fails is skipped for a while (see brain_fallback), so
            # a used-up free tier doesn't slow down every later question.
            #
            # The local model is no longer in this chain by default: it was
            # deleted in Aug 2026, and the whole point of v2 is that Rohan's PC
            # stays light. `VONDO_BRAIN=ollama` still reaches it if reinstalled.
            from core.brains.brain_groq import GroqBrain
            tail = FreeBrain()
            try:
                from core.brains.brain_gemini import GeminiBrain
                tail = FallbackBrain(GeminiBrain(), tail)
            except Exception as exc:  # noqa: BLE001  (no key / package)
                print(f"[gemini unavailable as a backup ({exc})]")
            return FallbackBrain(GroqBrain(), tail)
        if choice == "gemini":
            from core.brains.brain_gemini import GeminiBrain
            return FallbackBrain(GeminiBrain(), FreeBrain())
        if choice == "groq":
            from core.brains.brain_groq import GroqBrain
            return FallbackBrain(GroqBrain(), FreeBrain())
        if choice == "ollama":
            from core.brains.brain_ollama import OllamaBrain
            return FallbackBrain(OllamaBrain(), FreeBrain())
        if choice == "claude":
            from core.brains.brain_claude import ClaudeBrain
            return FallbackBrain(ClaudeBrain(), FreeBrain())
        if choice == "free":
            return FreeBrain()
        print(f"[unknown VONDO_BRAIN '{choice}', using offline 'free' brain]")
    except ImportError as exc:
        print(f"[missing package for '{choice}' brain: {exc}. "
              f"Run: pip install -r requirements/cloud.txt]")
    except Exception as exc:  # noqa: BLE001  (e.g. missing API key)
        print(f"[couldn't start '{choice}' brain: {exc}]")
    print("[falling back to the offline rule-based brain]")
    from core.brains.brain_free import FreeBrain
    return FreeBrain()
