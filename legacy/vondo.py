"""VONDO — a voice assistant for your PC.

Run:  python legacy/vondo.py
Change the brain (gemini / groq / claude / free) and options in your .env file.
"""
from __future__ import annotations

# --- repo-root bootstrap -------------------------------------------------
# These scripts are launched directly (double-clicked via the .bat files), so
# Python puts legacy/ on sys.path, not the repo root -- and `core` would not be
# importable. Sibling imports below (voice, vondo) still resolve normally.
import os as _os
import sys as _sys

_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
# -------------------------------------------------------------------------

import difflib
import sys

from core import config
from core.brains import factory
from core import reminders
from voice import Voice

# Accept common speech-to-text mis-hearings of the wake word too, so it still
# triggers reliably. ("Jarvis" is recognised well, but these cover slips.)
WAKE_VARIANTS = {
    config.WAKE_WORD, "jarvis", "jervis", "javis", "jarvi", "jarwis", "charvis",
    "harvis", "service", "jervais", "jarvis's",
}

# Longest first, and ORDER MATTERS. Several variants are prefixes of others:
# "jarvi" sits inside "jarvis", which sits inside "jarvis's". Iterating the set
# directly meant whichever happened to come up first won, and Python randomises
# string hashing per process — so "jarvis open chrome" split on "jarvi" and left
# the command as "s open chrome" on some runs and not others. That is what an
# assistant that "sometimes mishears you" actually looks like.
_VARIANTS_LONGEST_FIRST = sorted(WAKE_VARIANTS, key=len, reverse=True)


def match_wake(heard: str):
    """Return the command after the wake word, or None if no wake word heard.

    Returns '' when the wake word was heard but no command followed.
    """
    if not heard:
        return None
    for variant in _VARIANTS_LONGEST_FIRST:
        if variant in heard:
            return heard.split(variant, 1)[1].strip()
    # Fuzzy: is the first spoken word close enough to the wake word?
    first = heard.split()[0]
    if difflib.get_close_matches(first, [config.WAKE_WORD, "vondo"], n=1, cutoff=0.6):
        return heard.split(" ", 1)[1].strip() if " " in heard else ""
    return None


def make_brain(choice: str | None = None):
    """Build a brain that remembers the conversation and falls back gracefully.

    The construction itself lives in core.brains.factory so the cloud server and
    this desktop app build brains identically. Kept as a name here because the
    window's brain dropdown calls it.
    """
    return factory.make(choice)


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
