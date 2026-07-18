"""VONDO — a voice assistant for your PC.

Run:  python vondo.py
Change the brain (gemini / groq / claude / free) and options in your .env file.
"""
from __future__ import annotations

import difflib
import sys

import config
import confirm
import memory
import reminders
from voice import Voice

# Accept common speech-to-text mis-hearings of the wake word too, so it still
# triggers reliably. ("Jarvis" is recognised well, but these cover slips.)
WAKE_VARIANTS = {
    config.WAKE_WORD, "jarvis", "jervis", "javis", "jarvi", "jarwis", "charvis",
    "harvis", "service", "jervais", "jarvis's",
}


def match_wake(heard: str):
    """Return the command after the wake word, or None if no wake word heard.

    Returns '' when the wake word was heard but no command followed.
    """
    if not heard:
        return None
    for variant in WAKE_VARIANTS:
        if variant in heard:
            return heard.split(variant, 1)[1].strip()
    # Fuzzy: is the first spoken word close enough to the wake word?
    first = heard.split()[0]
    if difflib.get_close_matches(first, [config.WAKE_WORD, "vondo"], n=1, cutoff=0.6):
        return heard.split(" ", 1)[1].strip() if " " in heard else ""
    return None


def make_brain(choice: str | None = None):
    """Build a brain that remembers the conversation and falls back gracefully.

    Pass `choice` to build a specific brain (the UI dropdown does this when you
    switch); leave it out to use whatever VONDO_BRAIN says in .env.
    """
    # Wrapping the whole chain means every exchange is recorded once, whichever
    # brain in it answered — which is what lets the local model carry on a
    # conversation the cloud started. Both the window and the console build
    # brains through here, so nothing else needs to know about it.
    #
    # confirm sits inside memory: a "yes" answering "shut down the PC?" still
    # gets remembered as a normal exchange, but the model never sees the bare
    # "yes" — it has no idea an action was parked, and would only guess.
    return memory.wrap(confirm.wrap(_build_brain(choice)))


def _build_brain(choice: str | None = None):
    """Build the brain itself, wrapped so it auto-drops to the offline brain if
    the AI service is ever rate-limited or unreachable."""
    from brain_free import FreeBrain
    from brain_fallback import FallbackBrain, LazyBrain

    def _lazy_ollama():
        """The local model, wrapped so it only starts if it's actually reached."""
        from brain_ollama import OllamaBrain
        return LazyBrain(OllamaBrain, "ollama")

    choice = (choice or config.BRAIN).strip().lower()
    try:
        if choice == "auto":
            # Groq first: fastest, and nothing runs on this PC while it lasts.
            # Then the local model — no daily limit and no network round trip.
            # Gemini after that, and the rule-based brain as a last resort.
            # A brain that fails is skipped for a while (see brain_fallback), so
            # a used-up free tier doesn't slow down every later question.
            from brain_groq import GroqBrain
            tail = FreeBrain()
            try:
                from brain_gemini import GeminiBrain
                tail = FallbackBrain(GeminiBrain(), tail)
            except Exception as exc:  # noqa: BLE001  (no key / package)
                print(f"[gemini unavailable as a backup ({exc})]")
            return FallbackBrain(GroqBrain(), FallbackBrain(_lazy_ollama(), tail))
        if choice == "gemini":
            from brain_gemini import GeminiBrain
            return FallbackBrain(GeminiBrain(), FreeBrain())
        if choice == "groq":
            from brain_groq import GroqBrain
            return FallbackBrain(GroqBrain(), FreeBrain())
        if choice == "ollama":
            from brain_ollama import OllamaBrain
            return FallbackBrain(OllamaBrain(), FreeBrain())
        if choice == "claude":
            from brain_claude import ClaudeBrain
            return FallbackBrain(ClaudeBrain(), FreeBrain())
        if choice == "free":
            return FreeBrain()
        print(f"[unknown VONDO_BRAIN '{choice}', using offline 'free' brain]")
    except ImportError as exc:
        print(f"[missing package for '{choice}' brain: {exc}. Run: pip install -r requirements.txt]")
    except Exception as exc:  # noqa: BLE001  (e.g. missing API key)
        print(f"[couldn't start '{choice}' brain: {exc}]")
    print("[falling back to the offline rule-based brain]")
    return FreeBrain()


def wants_action(voice: Voice, brain) -> str:
    """Get the next command, honouring wake-word vs continuous listening mode."""
    if config.LISTEN_MODE == "continuous":
        return voice.listen()

    # Wake-word mode: wait to hear the wake word, then listen for the command.
    heard = voice.listen(timeout=None, phrase_limit=5)
    after = match_wake(heard)
    if after is None:
        return ""  # no wake word heard
    if after:
        return after  # command followed the wake word in the same phrase
    voice.say("Yes?")
    return voice.listen()


def main() -> None:
    booted = "--boot" in sys.argv  # launched automatically at PC startup?
    voice = Voice()
    reminders.start(voice.say)  # background thread that speaks reminders when due
    brain = make_brain()
    print(f"[{config.ASSISTANT_NAME} brain: {brain.name} | listen mode: {config.LISTEN_MODE} | "
          f"wake word: '{config.WAKE_WORD}']")
    voice.say(config.boot_greeting() if booted else brain.greeting())

    while True:
        try:
            command = wants_action(voice, brain)
            if not command:
                continue
            reply = brain.handle(command)
            if reply == "__EXIT__":
                voice.say("Goodbye.")
                break
            if reply:
                voice.say(reply)
        except KeyboardInterrupt:
            voice.say("Powering down.")
            break
        except Exception as exc:  # noqa: BLE001  keep the loop alive
            print(f"[error: {exc}]")


if __name__ == "__main__":
    sys.exit(main())
