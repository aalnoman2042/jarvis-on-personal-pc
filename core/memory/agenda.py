"""What is coming — the half of memory that points forwards.

Everything else in this package records what already happened. This records what
has not happened yet, which needs different rules:

* **It has to survive the process.** The old `core/reminders.py` kept a list in
  RAM and a thread to watch it. On the desktop that was fine. In the cloud the
  thread was never started and the list died with the request, so "remind me
  about my exam" was accepted, acknowledged, and thrown away — the single worst
  failure this project has had, because it looked like it worked.
* **A thing that happens and a warning about it are different times.** An exam
  on the 18th is no use announced as the invigilator hands out papers. So a row
  carries `due` (when the thing is) and `remind_at` (when to say something),
  which are usually the same and sometimes a day apart.
* **"18 September" has no time in it.** `all_day` keeps that distinction, so
  Jarvis says "on the 18th" rather than confidently inventing nine in the
  morning and being believed.

Same contract as the rest of the package: nothing here raises into a
conversation. A database that has gone away means "nothing scheduled", which is
wrong but survivable, exactly as `store` treats "nothing remembered".
"""
from __future__ import annotations

from core import clock
from core.memory import store

MAX_TEXT = store.MAX_TEXT
KINDS = ("reminder", "event", "checkin")


def _clean(text: str) -> str:
    return " ".join((text or "").split())[:MAX_TEXT]


def add(due: float, message: str, remind_at: float | None = None,
        all_day: bool = False, kind: str = "reminder", device: str = "",
        parent: int = 0) -> int | None:
    """Put something in the diary. Returns its id, or None if nothing was stored."""
    conn = store.connect()
    message = _clean(message)
    if conn is None or not message or not due:
        return None
    try:
        cursor = conn.execute(
            "INSERT INTO reminders(due, remind_at, message, created, fired, "
            "all_day, kind, device, parent) VALUES (?,?,?,?,0,?,?,?,?)",
            (float(due), float(remind_at if remind_at is not None else due), message,
             round(clock.now(), 1), 1 if all_day else 0,
             kind if kind in KINDS else "reminder", device or "", int(parent)),
        )
        conn.commit()
        return cursor.lastrowid
    except Exception:  # noqa: BLE001
        return None


def upcoming(limit: int = 20, within: float | None = None) -> list[dict]:
    """What is still ahead, soonest first.

    Ahead means `due` is in the future — not `remind_at`. Something already
    warned about is still on the agenda until it actually happens, which is what
    anyone means by "what's coming up".
    """
    conn = store.connect()
    if conn is None:
        return []
    now = clock.now()
    ceiling = now + within if within else float("inf")
    try:
        rows = conn.execute(
            "SELECT id, due, remind_at, message, created, fired, all_day, kind "
            "FROM reminders WHERE due >= ? AND due <= ? ORDER BY due ASC LIMIT ?",
            (now - 60, ceiling if ceiling != float("inf") else 1e12, limit),
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [dict(r) for r in rows]


def ready(now: float | None = None) -> list[dict]:
    """Everything whose moment to be said has arrived and which has not been said.

    Deliberately not time-boxed at the near end: a server that was asleep for
    three hours — which is exactly what a free tier does — must deliver what it
    slept through, late, rather than skip it for being stale. Late is a bad
    reminder; silent is a broken one.
    """
    conn = store.connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id, due, remind_at, message, all_day, kind FROM reminders "
            "WHERE fired = 0 AND remind_at <= ? ORDER BY remind_at ASC",
            (clock.now() if now is None else now,),
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [dict(r) for r in rows]


def mark_fired(reminder_id: int) -> None:
    """Record that this one has been delivered, so it is not delivered again."""
    conn = store.connect()
    if conn is None:
        return
    try:
        conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (int(reminder_id),))
        conn.commit()
    except Exception:  # noqa: BLE001
        pass


def cancel(fragment: str) -> int:
    """Drop everything still ahead that matches. 'all' clears the lot.

    Only future items: cancelling a reminder should never quietly rewrite the
    record of one that already went off.
    """
    conn = store.connect()
    fragment = (fragment or "").strip().lower()
    if conn is None or not fragment:
        return 0
    try:
        if fragment in ("all", "everything"):
            rows = conn.execute("SELECT id FROM reminders WHERE due >= ?",
                                (clock.now(),)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM reminders WHERE due >= ? AND lower(message) LIKE ?",
                (clock.now(), f"%{fragment}%"),
            ).fetchall()
        ids = [r["id"] for r in rows]
        for one in ids:
            conn.execute("DELETE FROM reminders WHERE id = ?", (one,))
            # A check-in only exists to ask about its parent. Left behind, it
            # would arrive days later asking how the preparation is going for
            # something that was cancelled.
            conn.execute("DELETE FROM reminders WHERE parent = ?", (one,))
        conn.commit()
        return len(ids)
    except Exception:  # noqa: BLE001
        return 0


def cancel_id(item_id: int) -> bool:
    """Drop one item by id — what a delete button on the dashboard does."""
    conn = store.connect()
    if conn is None:
        return False
    try:
        cursor = conn.execute("DELETE FROM reminders WHERE id = ?", (int(item_id),))
        conn.execute("DELETE FROM reminders WHERE parent = ?", (int(item_id),))
        conn.commit()
        return bool(cursor.rowcount)
    except Exception:  # noqa: BLE001
        return False


def count() -> int:
    """How many things are still ahead."""
    conn = store.connect()
    if conn is None:
        return 0
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM reminders WHERE due >= ?",
                           (clock.now(),)).fetchone()
    except Exception:  # noqa: BLE001
        return 0
    return int(row["n"]) if row else 0


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------

def describe(item: dict, base: float | None = None) -> str:
    """One line for a model or a screen: "exam — on 18th September (in 22 days)"."""
    when = clock.say(item["due"], bool(item.get("all_day")), base)
    return f"{item['message']} — {when} ({clock.until(item['due'], base)})"


def block(limit: int = 8) -> str:
    """The agenda, as a paragraph to hand a model with the system prompt.

    Kept short on purpose. This is prepended to every single turn, so it earns
    its tokens only while it stays a handful of lines.
    """
    items = upcoming(limit)
    if not items:
        return ""
    lines = "\n".join(f"- {describe(item)}" for item in items)
    return ("\n\nOn the agenda (do not repeat these unless asked or relevant):\n"
            + lines)
