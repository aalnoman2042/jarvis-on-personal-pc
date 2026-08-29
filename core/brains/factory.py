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


# Small, cheap, and answerable by anything that works. Not "hello", which some
# models answer with a paragraph; a sum has one short right answer and a wrong
# one is as informative as an error.
HEALTH_QUESTION = "Reply with only the number: what is 2 plus 2?"


def _groq_maker():
    def start():
        from core.brains.brain_groq import GroqBrain
        return GroqBrain()
    return start


def _gemini_maker():
    def start():
        from core.brains.brain_gemini import GeminiBrain
        return GeminiBrain()
    return start


def _extra_maker(name, url, key, model):
    def start():
        from core.brains.brain_openai import OpenAIBrain
        return OpenAIBrain(name, url, key, model)
    return start


def health() -> list[dict]:
    """Ask every configured brain one question, and report who actually answers.

    Being in the chain proves the key was present and the client was built. It
    does NOT prove the key is valid, the model still exists, or that the
    provider supports tool calling — all of which fail at the first real
    question, which by definition is the moment the brain before it ran out.
    Finding that out then is finding out at the worst possible time.

    Makes a real API call per brain, so it is on demand only and never on a
    timer. The offline brain is skipped: it always works, which is its whole
    job, and asking costs a web search.
    """
    import time

    from core import config

    checks = [("groq", _groq_maker()), ("gemini", _gemini_maker())]
    for name, url, key, model in config.extra_brains():
        checks.append((name, _extra_maker(name, url, key, model)))

    out = []
    for name, maker in checks:
        started = time.time()
        try:
            brain = maker()
        except Exception as exc:  # noqa: BLE001
            out.append({"brain": name, "ok": False, "ms": 0,
                        "why": f"could not start: {str(exc)[:120]}"})
            continue
        try:
            said = str(brain.handle(HEALTH_QUESTION) or "").strip()
        except Exception as exc:  # noqa: BLE001
            out.append({"brain": name, "ok": False,
                        "ms": int((time.time() - started) * 1000),
                        "why": f"{type(exc).__name__}: {str(exc)[:120]}"})
            continue
        # A brain that replies but gets it wrong is still reachable, and that
        # is the thing being tested — so the answer is reported rather than
        # graded. "4" is a working provider; a paragraph about arithmetic is a
        # working provider with a chatty model.
        out.append({"brain": name, "ok": True,
                    "ms": int((time.time() - started) * 1000),
                    "said": said[:120]})
    return out


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

    def _extra(name: str, url: str, key: str, model: str):
        def start():
            from core.brains.brain_openai import OpenAIBrain
            return OpenAIBrain(name, url, key, model)
        return start

    # Groq first: fastest and free. Gemini second: free, and the only one that
    # sees images. Then anything configured through VONDO_BRAIN_n — those exist
    # so that "both free tiers are spent" stops meaning "answered by something
    # that cannot think". Claude only when explicitly chosen: it is the paid one.
    PREFERRED = (("groq", _groq), ("gemini", _gemini)) + tuple(
        (name, _extra(name, url, key, model))
        for name, url, key, model in config.extra_brains())

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
