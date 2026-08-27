"""The people Rohan deals with, and how to reach them.

A phone number used to be a sentence in `facts` — "Rohan's dad's number is
+8801…" — which meant "call dad" depended on a model finding the right sentence
among dozens and reading the digits out of it correctly, every time, with no
way to tell whether it had. A number is structured data and it belongs in a
column, where it can be looked up exactly.

Three rules shape this:

* **One entry per name.** There is one "dad". Saying the number again corrects
  it rather than leaving two rows and a coin toss.
* **Numbers are stored as given and cleaned when used.** Rohan says "oh one
  seven one two…", pastes "+880 1712-345678", or types it with brackets; the
  dialler wants digits. Cleaning on the way in would throw away the form he
  recognises when reading it back.
* **Nothing here raises**, exactly like the rest of the package. Not finding a
  contact means asking for the number, which is a conversation, not an error.
"""
from __future__ import annotations

import re

from core import clock
from core.memory import store

MAX_NAME = 60
MAX_VALUE = 120


def _clean(text: str, limit: int = MAX_VALUE) -> str:
    return " ".join((text or "").split())[:limit]


def dialable(raw: str) -> str:
    """What a dialler will accept: digits, and a leading + if there was one."""
    kept = re.sub(r"[^\d+]", "", raw or "")
    # A + is only meaningful at the front. "+880+17" is somebody's typo.
    return ("+" if kept.startswith("+") else "") + kept.replace("+", "")


def remember(name: str, phone: str = "", email: str = "", note: str = "") -> str:
    """Add or update someone. Returns the sentence to say back."""
    conn = store.connect()
    name = _clean(name, MAX_NAME)
    if conn is None or not name:
        return "I need a name to save that against."
    phone, email, note = _clean(phone), _clean(email), _clean(note)
    if not (phone or email or note):
        return f"What should I remember about {name}?"

    existing = find(name)
    try:
        if existing:
            # Only what was actually given is replaced. Adding an email must not
            # silently wipe a number that took a conversation to obtain.
            conn.execute(
                "UPDATE contacts SET phone = ?, email = ?, note = ? WHERE id = ?",
                (phone or existing["phone"], email or existing["email"],
                 note or existing["note"], existing["id"]))
            conn.commit()
            return f"Updated {name}."
        conn.execute(
            "INSERT INTO contacts(name, phone, email, note, created) VALUES (?,?,?,?,?)",
            (name, phone, email, note, round(clock.now(), 1)))
        conn.commit()
    except Exception:  # noqa: BLE001
        return "I couldn't save that just now."
    return f"Saved {name}."


def find(name: str) -> dict | None:
    """The one person that name means, or None.

    Exact first, then a prefix, then anywhere in the name. "dad" should find
    "Dad" instantly; "rif" should find "Rifat" without matching "Sharif".
    """
    conn = store.connect()
    name = _clean(name, MAX_NAME).lower()
    if conn is None or not name:
        return None
    try:
        for sql, arg in (
            ("SELECT * FROM contacts WHERE lower(name) = ? LIMIT 1", name),
            ("SELECT * FROM contacts WHERE lower(name) LIKE ? ORDER BY length(name) LIMIT 1",
             f"{name}%"),
            ("SELECT * FROM contacts WHERE lower(name) LIKE ? ORDER BY length(name) LIMIT 1",
             f"%{name}%"),
        ):
            row = conn.execute(sql, (arg,)).fetchone()
            if row:
                return dict(row)
    except Exception:  # noqa: BLE001
        return None
    return None


def touch(contact_id: int) -> None:
    """Note that someone was just contacted, so the list sorts by use."""
    conn = store.connect()
    if conn is None:
        return
    try:
        conn.execute("UPDATE contacts SET used = ? WHERE id = ?",
                     (round(clock.now(), 1), int(contact_id)))
        conn.commit()
    except Exception:  # noqa: BLE001
        pass


def everyone(limit: int = 50) -> list[dict]:
    """All of them, most recently used first."""
    conn = store.connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT * FROM contacts ORDER BY used DESC, name ASC LIMIT ?",
            (limit,)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [dict(r) for r in rows]


def forget(name: str) -> bool:
    conn = store.connect()
    person = find(name)
    if conn is None or not person:
        return False
    try:
        conn.execute("DELETE FROM contacts WHERE id = ?", (person["id"],))
        conn.commit()
        return True
    except Exception:  # noqa: BLE001
        return False


def count() -> int:
    conn = store.connect()
    if conn is None:
        return 0
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()
    except Exception:  # noqa: BLE001
        return 0
    return int(row["n"]) if row else 0


def block(limit: int = 12) -> str:
    """The names, for the system prompt.

    Names only — never the numbers. The model has to know WHO exists so it can
    say "I don't have a number for Rifat" instead of inventing one, but putting
    a dozen phone numbers into every single prompt is both wasteful and the
    easiest way for one to end up somewhere it should not be. The number is
    fetched by the tool at the moment it is dialled.
    """
    people = everyone(limit)
    if not people:
        return ""
    names = ", ".join(p["name"] for p in people)
    return ("\n\nPeople you have contact details for (use call_contact or "
            f"message_contact by name; do not guess numbers): {names}.")
