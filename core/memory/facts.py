"""Things worth keeping for good.

The conversation is a rolling window — say something twenty turns ago and the
model no longer sees it. Facts are the opposite: short notes that ride along
with *every* question, forever. "Rohan works night shifts."

They are capped by rendered size rather than count, because unlike the
conversation these are re-sent on every single request to every brain. A list
that grew without limit would quietly eat the daily free allowance.

Storage moved from `jarvis.facts.json` to the facts table, but the rules above
and every function signature are unchanged.
"""
from __future__ import annotations

import time

from core import config
from core.memory import store


def facts() -> list[str]:
    """Everything Jarvis has been told to remember, oldest first."""
    conn = store.connect()
    if conn is None:
        return []
    try:
        rows = conn.execute("SELECT fact FROM facts ORDER BY id").fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [r["fact"] for r in rows]


def _third_person(fact: str) -> str:
    """Rewrite "your birthday is..." as "Rohan's birthday is...".

    Facts get read back to the model as notes *about* the user, so a fact stored
    as "you" or "I" reads as being about the wrong person. Small models write it
    either way whatever the tool description asks, so fix it here instead.
    """
    who = config.USER_TITLE or "the user"
    swaps = (
        ("your ", f"{who}'s "), ("you're ", f"{who} is "), ("you are ", f"{who} is "),
        ("you ", f"{who} "), ("my ", f"{who}'s "), ("i'm ", f"{who} is "),
        ("i am ", f"{who} is "), ("i ", f"{who} "),
    )
    low = fact.lower()
    for prefix, replacement in swaps:
        if low.startswith(prefix):
            return replacement + fact[len(prefix):]
    return fact


def _trim_to_cap(conn) -> None:
    """Drop the oldest facts once the list is full.

    Oldest go first — the newest thing you said matters most.
    """
    try:
        conn.execute(
            "DELETE FROM facts WHERE id NOT IN "
            "(SELECT id FROM facts ORDER BY id DESC LIMIT ?)",
            (config.MEMORY_MAX_FACTS,),
        )
    except Exception:  # noqa: BLE001
        pass


def add(fact: str) -> str:
    """Remember something for good. Returns a line to say back."""
    fact = " ".join((fact or "").split())  # collapse dictated whitespace
    fact = _third_person(fact)
    if not fact:
        return "There was nothing to remember."
    if not config.MEMORY_ENABLED:
        return "My memory is switched off at the moment."
    conn = store.connect()
    if conn is None:
        return "My memory is switched off at the moment."
    try:
        # The UNIQUE COLLATE NOCASE index does the duplicate check for us, so
        # "Rohan likes tea" and "rohan likes TEA" cannot both be stored.
        cur = conn.execute(
            "INSERT OR IGNORE INTO facts(ts, fact) VALUES (?, ?)",
            (round(time.time(), 1), fact),
        )
        if not cur.rowcount:
            return "I already had that one."
        _trim_to_cap(conn)
        conn.commit()
    except Exception:  # noqa: BLE001
        return "I couldn't write that down just now."
    return f"Noted. I'll remember that {fact.rstrip('.')}."


def forget(fragment: str) -> str:
    """Drop remembered things matching a fragment. Returns a line to say back."""
    fragment = " ".join((fragment or "").split()).lower()
    if not fragment:
        return "Tell me what to forget."
    conn = store.connect()
    if conn is None:
        return "My memory is switched off at the moment."
    try:
        if fragment in ("all", "everything"):
            n = conn.execute("SELECT COUNT(*) AS n FROM facts").fetchone()["n"]
            conn.execute("DELETE FROM facts")
            conn.commit()
            return f"Forgotten, all {n} of them." if n else "There was nothing to forget."
        cur = conn.execute(
            "DELETE FROM facts WHERE instr(lower(fact), ?) > 0", (fragment,)
        )
        dropped = cur.rowcount
        conn.commit()
    except Exception:  # noqa: BLE001
        return "I couldn't change that just now."
    if not dropped:
        return f"I had nothing remembered about {fragment}."
    return f"Forgotten. That's {dropped} thing{'s' if dropped > 1 else ''} about {fragment}."


def block() -> str:
    """The facts as a line for the system prompt, or '' when there are none.

    Capped by rendered length, since this is re-sent with every single question.
    """
    kept, used = [], 0
    for fact in facts():
        line = fact.rstrip(".")
        if used + len(line) + 2 > config.MEMORY_FACTS_CHARS:
            break
        kept.append(line)
        used += len(line) + 2
    if not kept:
        return ""
    return (" Things you already know about them, remembered from earlier: "
            + "; ".join(kept) + ". Use these when relevant without mentioning "
            "that you looked them up.")
