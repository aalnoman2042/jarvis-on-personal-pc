"""Reaching the phone in your hand.

The other half of "my PC is off". `core.actions` opens things on the desktop,
which is right when the desktop is awake and useless when it is not — and the
device asking is a phone perfectly capable of opening YouTube itself.

**Android will not let one app drive another**, and nothing here pretends
otherwise. There is no reading another app's screen, no tapping its buttons, no
reading notifications. What an app *can* do is hand something off: a URL, a
phone number, a map reference, a pre-filled message. That is the whole of this
module, and it covers most of what anyone actually means by "open WhatsApp and
tell Rifat I'm late".

**How it reaches the phone.** The brain runs in the cloud, so it cannot open
anything itself; it leaves an instruction here and the server attaches it to the
reply going down the websocket. The client then follows it. One pending
instruction at a time is enough because turns are serialised behind the brain
lock — see `_answer` in server/app.py.
"""
from __future__ import annotations

import re
import threading

# Where a name should send you. Deep links where a real app exists to catch
# them, https where the browser is genuinely the better answer.
SHORTCUTS: dict[str, str] = {
    "youtube": "https://m.youtube.com",
    "google": "https://www.google.com",
    "gmail": "googlegmail://",
    "mail": "googlegmail://",
    "maps": "https://maps.google.com",
    "google maps": "https://maps.google.com",
    "whatsapp": "whatsapp://",
    "messenger": "fb-messenger://",
    "facebook": "https://m.facebook.com",
    "instagram": "https://instagram.com",
    "twitter": "https://twitter.com",
    "x": "https://twitter.com",
    "spotify": "spotify://",
    "telegram": "tg://",
    "chatgpt": "https://chat.openai.com",
    "github": "https://github.com",
    "drive": "https://drive.google.com",
    "google drive": "https://drive.google.com",
    "calendar": "https://calendar.google.com",
    "photos": "https://photos.google.com",
    "camera": "camera://",
    "settings": "app-settings:",
    "netflix": "https://netflix.com",
    "amazon": "https://amazon.in",
    "linkedin": "https://linkedin.com",
    "reddit": "https://reddit.com",
    "wikipedia": "https://wikipedia.org",
}

# What the client is told to do, set by a tool and taken by the server once the
# turn is finished. Lock rather than a bare global: the reminder sweep and a
# turn can touch this from different threads.
_lock = threading.Lock()
_pending: str = ""


def request(url: str) -> None:
    with _lock:
        global _pending
        _pending = url


def take() -> str:
    """The instruction for this turn, if any. Clears as it is read."""
    with _lock:
        global _pending
        url, _pending = _pending, ""
        return url


# Where Rohan's local numbers belong. VONDO_TZ already says Asia/Dhaka; this is
# the same fact in the form a phone number needs.
COUNTRY_CODE = __import__("os").getenv("VONDO_COUNTRY_CODE", "880").lstrip("+")


def _tidy_number(raw: str) -> str:
    """Strip a spoken number down to something a dialler accepts."""
    return re.sub(r"[^\d+]", "", raw or "")


def _international(raw: str) -> str:
    """A number in the form WhatsApp needs: country code, no plus, no leading 0.

    wa.me will not open a chat for a local number — "01812999888" silently does
    nothing, which looks exactly like the app being broken. A number saved the
    way it is written locally therefore has to be converted at the point of use,
    and only here: the dialler is perfectly happy with the local form, and
    rewriting what Rohan typed would make it unrecognisable when read back.
    """
    digits = _tidy_number(raw)
    if digits.startswith("+"):
        return digits[1:]
    if digits.startswith("00"):
        return digits[2:]
    if digits.startswith(COUNTRY_CODE) and len(digits) > len(COUNTRY_CODE) + 6:
        return digits
    # A local number: drop the trunk zero and put the country code on.
    return COUNTRY_CODE + digits.lstrip("0")


def resolve(target: str) -> tuple[str, str]:
    """Turn what was said into (url, what to say back).

    Returns ("", reason) when there is nothing sensible to open, so the caller
    can say why rather than opening a search for a typo.
    """
    name = " ".join((target or "").strip().lower().split())
    if not name:
        return "", "Open what?"

    name = re.sub(r"^(?:the\s+)?(?:app|website|site)\s+", "", name)
    name = re.sub(r"\s+(?:app|website|site)$", "", name)

    if name in SHORTCUTS:
        return SHORTCUTS[name], name

    # A full URL, or something that looks like a domain.
    if re.match(r"^https?://", name):
        return name, name
    if re.match(r"^[\w-]+(\.[\w-]+)+(/.*)?$", name):
        return f"https://{name}", name

    # Anything else: search for it rather than guessing at a package name.
    # Being honest about what happened matters — "I don't have that app" would
    # be a claim this cannot actually check.
    from urllib.parse import quote_plus
    return f"https://www.google.com/search?q={quote_plus(name)}", name


def open_app(target: str) -> str:
    """Open something on the phone: an app by name, a site, or a URL."""
    url, label = resolve(target)
    if not url:
        return label
    request(url)
    return f"Opening {label}."


def call(number: str, who: str = "") -> str:
    """Bring up the dialler with a number in it.

    Deliberately does not place the call. Dialling on someone's behalf from a
    misheard sentence is not a mistake you can take back, and the extra tap
    costs nothing.
    """
    digits = _tidy_number(number)
    if len(digits) < 3:
        return "I need a number to call."
    request(f"tel:{digits}")
    return f"Calling {who or digits} — press dial."


def message(number: str, text: str = "", who: str = "") -> str:
    """Open WhatsApp on a chat, with the message already typed.

    Again: typed, not sent. Same reasoning as the dialler — the last tap stays
    with the person whose name is on the message.
    """
    from urllib.parse import quote
    digits = _international(number)
    if len(digits) < 6:
        return "I need a number to message."
    body = f"&text={quote(text)}" if text else ""
    request(f"https://wa.me/{digits}?{body.lstrip('&')}")
    return f"Message to {who or digits} is ready — press send."


def navigate(place: str) -> str:
    """Open maps, pointed at somewhere."""
    from urllib.parse import quote_plus
    where = " ".join((place or "").split())
    if not where:
        return "Navigate where?"
    request(f"https://www.google.com/maps/search/?api=1&query={quote_plus(where)}")
    return f"Directions to {where}."
