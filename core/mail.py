"""Reading Rohan's inboxes — several of them, over IMAP, and never writing.

**Why IMAP and not the Gmail API.** The official route is OAuth: a Google Cloud
project, a consent screen, and — for an app Google has not verified — refresh
tokens that expire every seven days. A personal assistant that stops working
every Sunday until you re-authorise is not a personal assistant. An app password
is one string, never expires, works against Gmail and everything else with the
same code, and costs no account anywhere.

**Read-only is enforced, not intended.** Every mailbox is selected with
`readonly=True` and every fetch uses `BODY.PEEK`, which is the form of FETCH
that does not set the Seen flag. Nothing here sends, deletes, moves or marks.
The credentials could do all of those; the code cannot.

**Priority is worked out locally.** Scoring is rules over headers — who it is
from, whether it was addressed to you or to a list, whether the subject sounds
like a deadline — and costs nothing. A model is involved only when a written
summary is asked for, so checking mail all day is free.

**Nothing is stored.** No message body reaches the database. Mail is fetched,
ranked, shown, and forgotten; the archive is the mail server's job and it is
already doing it. A summary Jarvis speaks is recorded like any other reply, but
the mail itself is not copied anywhere.
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import logging
import os
import re
import socket
from dataclasses import dataclass, field
from email.header import decode_header, make_header

from core import clock

log = logging.getLogger("vondo.mail")

# IMAP over a bad connection can hang for minutes. A turn must not.
TIMEOUT = 20.0
# Headers are small; this is about not fetching a thousand of them on a phone.
MAX_PER_BOX = 40
SNIPPET = 240


@dataclass
class Account:
    label: str
    host: str
    port: int
    user: str
    password: str = field(repr=False)


@dataclass
class Message:
    account: str
    uid: str
    sender: str
    sender_name: str
    subject: str
    date: float
    unread: bool
    to_me: bool
    bulk: bool
    snippet: str
    score: int = 0
    why: str = ""


# ---------------------------------------------------------------------------
# Which mailboxes
# ---------------------------------------------------------------------------

# The IMAP host for the providers worth guessing. Typing a hostname correctly
# into a dashboard is a surprising amount of the failure surface, and for a
# gmail.com address there is exactly one right answer.
KNOWN_HOSTS = {
    "gmail.com": "imap.gmail.com",
    "googlemail.com": "imap.gmail.com",
    "outlook.com": "outlook.office365.com",
    "hotmail.com": "outlook.office365.com",
    "live.com": "outlook.office365.com",
    "office365.com": "outlook.office365.com",
    "yahoo.com": "imap.mail.yahoo.com",
    "icloud.com": "imap.mail.me.com",
    "me.com": "imap.mail.me.com",
    "proton.me": "127.0.0.1",       # Proton needs its local bridge
    "zoho.com": "imap.zoho.com",
    "yandex.com": "imap.yandex.com",
}


def _guess_host(address: str) -> str:
    domain = address.rsplit("@", 1)[-1].lower().strip()
    if domain in KNOWN_HOSTS:
        return KNOWN_HOSTS[domain]
    # A university mailbox is very often Google or Microsoft underneath, but
    # guessing wrong is worse than asking, so this only prefixes the domain —
    # imap.uni.edu is right often enough to be worth trying and obvious enough
    # to correct when it is not.
    return f"imap.{domain}" if domain else ""


def _looks_like_a_secret(text: str) -> int:
    """How much a field looks like an app password rather than a label.

    Google issues sixteen lowercase letters and displays them in four groups of
    four, so the spaces belong to the presentation and not the value. A label is
    a word someone chose — "Personal", "University" — which is shorter, usually
    capitalised, and may contain a space that matters.
    """
    squashed = text.replace(" ", "")
    if not squashed:
        return -99
    points = 0
    if len(squashed) == 16:
        points += 3                       # exactly Google's shape
    if len(squashed) >= 12:
        points += 2
    if squashed.isalnum():
        points += 1
    if squashed.islower():
        points += 1                       # app passwords have no capitals
    if len(squashed) <= 8:
        points -= 2                       # too short to be a credential
    return points


def _split_secret(leftovers: list[str]) -> tuple[str, str]:
    """(password, label) out of the fields that were neither address nor host."""
    if not leftovers:
        return ("", "")
    if len(leftovers) == 1:
        return (leftovers[0].replace(" ", ""), "")
    ranked = sorted(leftovers, key=_looks_like_a_secret, reverse=True)
    password = ranked[0].replace(" ", "")
    label = next((f for f in leftovers if f is not ranked[0]), "")
    return (password, label)


def accounts() -> list[Account]:
    """Every configured mailbox, read from VONDO_MAIL_1..9.

    The full form is five fields:

        Label|imap.host.com|993|address@host.com|app-password

    but almost none of that has to be typed. The address and the password are
    the only two things nothing can work out, so this is enough:

        you@gmail.com|abcdefghijklmnop

    Deliberately forgiving about how the fields are separated and how they are
    decorated. The strict version rejected both of Rohan's accounts and could
    only say "malformed", because these get typed into a hosting dashboard by
    hand and every way of getting that slightly wrong looks identical from here:
    a comma instead of a pipe, quotes around the value, the key name pasted in
    along with it, or the app password left with the spaces Google displays it
    with. Every one of those now parses.
    """
    found: list[Account] = []
    for i in range(1, 10):
        key = f"VONDO_MAIL_{i}"
        raw = os.getenv(key, "").strip()
        if not raw:
            continue

        # "VONDO_MAIL_1 = value" pasted whole, and surrounding quotes.
        raw = re.sub(r"^\s*VONDO_MAIL_\d+\s*=\s*", "", raw, flags=re.I)
        raw = raw.strip().strip('"').strip("'").strip()

        # Pipe is the documented separator; comma and semicolon are what people
        # reach for instead, and none of them can appear in a hostname or an
        # app password, so accepting all three costs nothing.
        parts = [p.strip().strip('"').strip("'")
                 for p in re.split(r"[|;,]", raw) if p.strip()]
        if not parts:
            log.warning("%s is empty after parsing", key)
            continue

        # Work out which field is which by what it looks like, rather than by
        # where it sits. An address contains @; a port is digits; a host has a
        # dot and no @. What is left over is the password, and then the label.
        address = next((p for p in parts if "@" in p and "." in p), "")
        port = next((int(p) for p in parts if p.isdigit() and len(p) <= 5), 993)
        host = next((p for p in parts
                     if "@" not in p and "." in p and not p.replace(".", "").isdigit()), "")
        leftovers = [p for p in parts
                     if p != address and p != host and not p.isdigit()]

        if not address:
            log.warning("%s: no email address found among %d field(s)", key, len(parts))
            continue

        # Which leftover is the password and which is the label, decided by what
        # they look like rather than by which came first. Taking the first one
        # read "Personal" out of the documented form as the password and the
        # real password as the label — quietly, since a wrong password only
        # shows up later as a login failure.
        password, label = _split_secret(leftovers)

        if not password:
            log.warning("%s: found an address but no password (%d field(s))",
                        key, len(parts))
            continue

        host = host or _guess_host(address)
        if not host:
            log.warning("%s: could not work out an IMAP host for that address", key)
            continue

        found.append(Account(label or address, host, port, address, password))
        log.info("mailbox %d ready: %s via %s:%d", i, address, host, port)
    return found


def configured() -> bool:
    return bool(accounts())


# ---------------------------------------------------------------------------
# What matters
# ---------------------------------------------------------------------------

# Words that make a subject worth looking at. Deliberately about consequences
# and deadlines rather than about urgency — everything marketing sends says
# "urgent", and almost nothing that matters does.
URGENT = re.compile(
    r"\b(deadline|due|overdue|urgent|asap|action required|final notice|"
    r"interview|viva|exam|result|admission|scholarship|submission|submit|"
    r"reject|accept|approved|invoice|payment|fee|expire|expiring|reminder|"
    r"meeting|appointment|schedule|reschedule|cancelled|postponed)\b",
    re.I,
)

# The shape of mail nobody needs to be told about at breakfast.
NOISE = re.compile(
    r"\b(newsletter|unsubscribe|sale|discount|offer|deal|promo|webinar|"
    r"digest|no-?reply|noreply|notification|automated)\b",
    re.I,
)


def _clean(raw: str) -> str:
    """A header as text. Mail headers arrive encoded in a dozen ways."""
    if not raw:
        return ""
    try:
        return " ".join(str(make_header(decode_header(raw))).split())
    except Exception:  # noqa: BLE001  (a malformed header must not lose the message)
        return " ".join(raw.split())


def score(message: Message, known: set[str]) -> Message:
    """How much this one deserves attention, and a phrase saying why.

    Rules, not a model. Which means it is free to run on every message of every
    account all day, and — more importantly — that its reasoning can be printed
    next to the result instead of being a number nobody can argue with.
    """
    points = 0
    reasons: list[str] = []

    if message.unread:
        points += 2
    if message.bulk:
        points -= 4
    else:
        points += 2
        reasons.append("sent to you")
    if message.to_me:
        points += 2

    if NOISE.search(f"{message.subject} {message.sender}"):
        points -= 4
    hit = URGENT.search(message.subject)
    if hit:
        points += 4
        reasons.append(f"mentions {hit.group(0).lower()}")

    # Someone Jarvis already knows about — a supervisor, a person in the facts —
    # outranks a stranger saying the same words.
    address = message.sender.lower()
    name = message.sender_name.lower()
    if any(k and (k in address or k in name) for k in known):
        points += 4
        reasons.append("someone you know")

    age_hours = (clock.now() - message.date) / 3600 if message.date else 999
    if age_hours < 24:
        points += 2
    elif age_hours > 24 * 14:
        points -= 2

    message.score = points
    message.why = ", ".join(reasons)
    return message


def _known_names() -> set[str]:
    """Names Jarvis has been told about, lowercased, for sender matching."""
    try:
        from core.memory import facts as facts_mod
        words: set[str] = set()
        for fact in facts_mod.facts():
            for word in re.findall(r"[A-Z][a-z]{2,}", fact):
                words.add(word.lower())
        # The owner's own name is in every fact and would match everything.
        from core import config
        words.discard((config.USER_TITLE or "").lower())
        return words
    except Exception:  # noqa: BLE001
        return set()


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _fetch_box(account: Account, days: int, only_unread: bool) -> list[Message]:
    """Headers from one mailbox. Never raises — a dead account is skipped."""
    out: list[Message] = []
    box = None
    try:
        socket.setdefaulttimeout(TIMEOUT)
        box = imaplib.IMAP4_SSL(account.host, account.port)
        box.login(account.user, account.password)
        # readonly: the server itself refuses any change from this session.
        box.select("INBOX", readonly=True)

        since = clock.local(clock.now() - days * 86400).strftime("%d-%b-%Y")
        criteria = f'(SINCE "{since}")'
        if only_unread:
            criteria = f'(UNSEEN SINCE "{since}")'
        status, data = box.search(None, criteria)
        if status != "OK" or not data or not data[0]:
            return out

        ids = data[0].split()[-MAX_PER_BOX:]
        if not ids:
            return out

        # BODY.PEEK, not BODY: PEEK is the form that does not set \Seen. Using
        # plain BODY here would mean Jarvis silently marked mail as read just by
        # looking at whether it mattered.
        status, chunks = box.fetch(
            b",".join(ids),
            "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE TO CC LIST-UNSUBSCRIBE"
            " PRECEDENCE AUTO-SUBMITTED)])",
        )
        if status != "OK":
            return out

        for chunk in chunks:
            if not isinstance(chunk, tuple) or len(chunk) < 2:
                continue
            meta = chunk[0].decode("utf-8", "replace") if isinstance(chunk[0], bytes) else str(chunk[0])
            raw = chunk[1] if isinstance(chunk[1], bytes) else b""
            header = email.message_from_bytes(raw)

            sender_name, sender = email.utils.parseaddr(_clean(header.get("From", "")))
            subject = _clean(header.get("Subject", "")) or "(no subject)"
            when = 0.0
            try:
                parsed = email.utils.parsedate_to_datetime(header.get("Date", ""))
                when = parsed.timestamp() if parsed else 0.0
            except Exception:  # noqa: BLE001
                when = 0.0

            recipients = f"{_clean(header.get('To',''))} {_clean(header.get('Cc',''))}".lower()
            bulk = bool(
                header.get("List-Unsubscribe")
                or header.get("Precedence")
                or header.get("Auto-Submitted")
            )
            uid = re.search(r"^(\d+)", meta)
            out.append(Message(
                account=account.label,
                uid=uid.group(1) if uid else "",
                sender=sender,
                sender_name=sender_name or sender,
                subject=subject,
                date=when,
                unread="\\Seen" not in meta,
                to_me=account.user.lower() in recipients,
                bulk=bulk,
                snippet="",
            ))
    except Exception as exc:  # noqa: BLE001  (one bad mailbox must not lose the rest)
        log.warning("mailbox %s failed: %s", account.label, exc)
    finally:
        try:
            if box is not None:
                box.logout()
        except Exception:  # noqa: BLE001
            pass
        socket.setdefaulttimeout(None)
    return out


def inbox(days: int = 3, only_unread: bool = False, limit: int = 12) -> list[Message]:
    """The most worth-reading mail across every account, best first."""
    known = _known_names()
    everything: list[Message] = []
    for account in accounts():
        everything.extend(_fetch_box(account, days, only_unread))
    ranked = [score(m, known) for m in everything]
    ranked.sort(key=lambda m: (-m.score, -m.date))
    return ranked[:limit]


# ---------------------------------------------------------------------------
# Saying it
# ---------------------------------------------------------------------------

def _line(message: Message) -> str:
    who = message.sender_name or message.sender
    when = clock.was(message.date) if message.date else ""
    tail = f" ({message.why})" if message.why else ""
    return f"{who}: {message.subject} — {when}{tail}"


def summary(days: int = 1, limit: int = 6) -> str:
    """What is in the inboxes, as a couple of spoken sentences.

    Composed rather than generated, for the same reason the morning briefing is:
    it has to work when the free tier is spent, it costs nothing to run every
    day forever, and a model asked to summarise a list of subjects will
    eventually report an email that is not there.
    """
    if not configured():
        return ("No mailboxes are connected yet. Add one and I'll keep an eye "
                "on it for you.")
    messages = inbox(days=days, limit=limit)
    if not messages:
        return "Nothing new worth your attention in the inbox."

    worth = [m for m in messages if m.score >= 4]
    if not worth:
        return f"{len(messages)} new, nothing that looks important."

    lines = "; ".join(_line(m) for m in worth[:4])
    rest = len(messages) - len(worth[:4])
    tail = f" And {rest} other{'s' if rest != 1 else ''}." if rest > 0 else ""
    return f"{len(worth)} worth a look. {lines}.{tail}"


def unread_count() -> int:
    """How many unread, across everything. Cheap enough for the board."""
    if not configured():
        return 0
    return len(inbox(days=7, only_unread=True, limit=999))
