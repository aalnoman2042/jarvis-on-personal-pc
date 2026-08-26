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

def accounts() -> list[Account]:
    """Every configured mailbox.

    Read from VONDO_MAIL_1..9, each one pipe-separated:

        Label|imap.host.com|993|address@host.com|app-password

    Numbered environment variables rather than one JSON blob because these are
    typed into a hosting dashboard by hand, and a misplaced brace in a secret is
    a bad afternoon. The port may be left out; 993 is assumed.
    """
    found: list[Account] = []
    for i in range(1, 10):
        raw = os.getenv(f"VONDO_MAIL_{i}", "").strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) == 4:                     # port omitted
            label, host, user, password = parts
            port = 993
        elif len(parts) == 5:
            label, host, port_text, user, password = parts
            try:
                port = int(port_text)
            except ValueError:
                port = 993
        else:
            log.warning("VONDO_MAIL_%d is malformed; expected 4 or 5 fields", i)
            continue
        if not (host and user and password):
            continue
        found.append(Account(label or user, host, port, user, password))
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
