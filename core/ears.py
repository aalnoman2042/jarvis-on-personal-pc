"""Turning a few seconds of audio into a sentence.

v1 listened with Google's free web speech API, which works because it runs on a
Windows desktop with a microphone attached. None of that survives the move: the
cloud core has no microphone, and the phone is the thing holding one.

So the phone records and the cloud transcribes. Groq's Whisper is on the same
free key as the brain, which means no new account, no new bill, and — because it
is the same provider — one thing to check when speech stops working.

**Doing it server-side is a choice, not a limitation.** The browser has a speech
API and Chrome on a laptop implements it well. The Android *WebView* the app
runs in usually does not, and a microphone that works in the browser but not in
the app is worse than one that works the same everywhere. The client may still
use the browser's own recogniser when it genuinely has one; this is what makes
the feature exist at all.

Never raises. A failed transcription comes back as "" and the caller says it did
not catch that — which is what a person would do.
"""
from __future__ import annotations

import logging
import os

from core import config

log = logging.getLogger("vondo.ears")

# turbo: about eight times cheaper in time than large-v3 and, for a phone
# holding a sentence, indistinguishable. Overridable because Groq retires model
# names without much warning — the same trap that took out llama-3.3.
WHISPER_MODEL = os.getenv("VONDO_WHISPER_MODEL", "whisper-large-v3-turbo")

# Whisper is told what language to expect rather than guessing. Guessing is what
# turns a short, accented English sentence into confident Welsh.
LANGUAGE = os.getenv("VONDO_STT_LANGUAGE", "en")

# Bigger than any sentence and small enough to refuse a mistake early. Groq's
# own ceiling on the free tier is far higher; this is about not accepting a
# 40 MB upload from something that is not the app.
MAX_BYTES = 8 * 1024 * 1024

_client = None


def available() -> bool:
    return bool(config.GROQ_API_KEY)


def _groq():
    global _client
    if _client is None:
        from groq import Groq  # imported late: the desktop may not have it
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


def _hint() -> str:
    """Words Whisper should expect to hear.

    Proper nouns are what a speech model gets wrong, and they are exactly the
    words that matter here — being called "Travis" by your own assistant is a
    small thing that makes it feel like it is not listening.
    """
    names = [config.ASSISTANT_NAME, config.USER_TITLE]
    return "Words that may appear: " + ", ".join(n for n in names if n) + "."


def transcribe(data: bytes, filename: str = "clip.webm") -> str:
    """Audio in, words out. Empty string if it could not be done."""
    if not data or not available():
        return ""
    if len(data) > MAX_BYTES:
        log.warning("audio too large: %d bytes", len(data))
        return ""
    try:
        result = _groq().audio.transcriptions.create(
            file=(filename, data),
            model=WHISPER_MODEL,
            language=LANGUAGE,
            prompt=_hint(),
            response_format="text",
        )
    except Exception as exc:  # noqa: BLE001  (a bad clip must not end the turn)
        log.warning("transcription failed: %s", exc)
        return ""
    # response_format="text" returns a plain string on most versions and an
    # object with .text on others. Both are handled rather than pinned, because
    # the SDK has changed this before.
    text = result if isinstance(result, str) else getattr(result, "text", "")
    words = " ".join(str(text).split())
    return "" if _is_hallucination(words) else words


# Whisper does not answer silence with silence. Trained on a lot of subtitled
# video, it fills a quiet clip with the things that pad the end of a subtitle
# file — a full stop, "Thank you", "The End", a credit line. Passed through,
# these become questions Jarvis earnestly answers, so an accidental tap produces
# a reply to "thanks for watching". Anything that is ONLY one of these, with no
# other words around it, did not contain speech.
_GHOSTS = {
    "", ".", "..", "...", "you", "thank you", "thank you.", "thanks",
    "thanks for watching", "thanks for watching.", "thank you for watching",
    "thank you for watching.", "the end", "the end.", "bye", "bye.",
    "please subscribe", "subscribe", "uh", "um",
    # Deliberately NOT here: "ok", "so", "yes", "no" — these are common Whisper
    # ghosts on silence, but they are also real one-word answers to "say yes to
    # confirm", and eating a real answer feels more broken than answering a
    # stray "ok".
}


def _is_hallucination(words: str) -> bool:
    clean = words.strip().lower()
    if not any(ch.isalnum() for ch in clean):
        return True  # punctuation only
    return clean in _GHOSTS
