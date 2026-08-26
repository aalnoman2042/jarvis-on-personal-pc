"""Looking at a picture and saying what is in it.

The one honest version of the movie's face-tracking panel. That prop identifies
strangers from a database nobody has; this describes what is actually in the
frame — a document, a screen, a room, a page of notes, a error message on a
monitor — which is the thing that is both possible and useful.

Gemini does the seeing, on the same free key as the backup brain. It reads
screenshots and photographs well; it was checked against real phone screenshots
before any of this was built. The point is not recognition, it is
comprehension: "what does this say", "what is wrong here", "read this to me".

Kept apart from `brain_gemini` on purpose. The brain holds a running
conversation with tools bound to it; a glance at an image is a single, stateless
question with no tools and no history, and mixing the two would drag the whole
tool schema into every photo. Never raises — a look that fails comes back as a
sentence saying so.
"""
from __future__ import annotations

import logging

from core import config

log = logging.getLogger("vondo.eyes")

# Flash reads an image in a second or two and is free. Overridable because
# Google renames these too, and a vision request to a retired name fails exactly
# the way a chat one does.
VISION_MODEL = __import__("os").getenv("VONDO_VISION_MODEL", config.GEMINI_MODEL)

# A phone photo is a couple of megabytes; a screenshot less. Ten is loose enough
# for a high-res camera and tight enough to refuse something that is not a photo.
MAX_BYTES = 10 * 1024 * 1024

# What to say when no question came with the picture. Open on purpose: the most
# common use is holding something up and asking, wordlessly, "what is this".
DEFAULT_PROMPT = (
    "Look at this image and tell me what it shows, briefly and plainly, the way "
    "you would describe it to someone who cannot see it. If it contains text, "
    "read the part that matters. If something looks wrong or needs attention, "
    "say so. One or two sentences unless there is genuinely more to tell."
)

_client = None


def available() -> bool:
    return bool(config.GEMINI_API_KEY)


def _gemini():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _mime(filename: str, data: bytes) -> str:
    """Best guess at the image type, from the name and then the bytes.

    Gemini needs a media type. The browser sends one, but a shared file may
    arrive with a generic name, so the magic numbers are the backstop.
    """
    name = (filename or "").lower()
    if name.endswith(".png") or data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if name.endswith((".jpg", ".jpeg")) or data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if name.endswith(".webp") or data[8:12] == b"WEBP":
        return "image/webp"
    if name.endswith(".gif") or data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"  # the browser's canvas exports jpeg by default


def look(data: bytes, question: str = "", filename: str = "image.jpg") -> str:
    """An image in, a description out. A plain sentence if it could not be done."""
    if not data:
        return "There was no image to look at."
    if not available():
        return "I can't see images just now — the vision key isn't set."
    if len(data) > MAX_BYTES:
        return "That image is too large for me to look at."

    from google.genai import types

    prompt = (question or "").strip() or DEFAULT_PROMPT
    try:
        response = _gemini().models.generate_content(
            model=VISION_MODEL,
            contents=[
                types.Part.from_bytes(data=data, mime_type=_mime(filename, data)),
                prompt,
            ],
        )
    except Exception as exc:  # noqa: BLE001  (a bad image must not end the turn)
        log.warning("vision failed: %s", exc)
        return "I couldn't make sense of that image just now."
    text = (getattr(response, "text", "") or "").strip()
    return text or "I looked, but I couldn't tell what that is."
