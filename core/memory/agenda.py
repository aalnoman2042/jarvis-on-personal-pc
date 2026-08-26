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
        parent: int = 0, repeat_rule: str = "", repeat_days: list | None = None) -> int | None:
    """Put something in the diary. Returns its id, or None if nothing was stored."""
    conn = store.connect()
    message = _clean(message)
    if conn is None or not message or not due:
        return None
    try:
        cursor = conn.execute(
            "INSERT INTO reminders(due, remind_at, message, created, fired, "
            "all_day, kind, device, parent, repeat_rule, repeat_days) "
            "VALUES (?,?,?,?,0,?,?,?,?,?,?)",
            (float(due), float(remind_at if remind_at is not None else due), message,
             round(clock.now(), 1), 1 if all_day else 0,
             kind if kind in KINDS else "reminder", device or "", int(parent),
             repeat_rule or "",
             ",".join(str(d) for d in (repeat_days or []))),
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
            "SELECT id, due, remind_at, message, created, fired, all_day, kind, "
            "repeat_rule, repeat_days "
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
            "SELECT id, due, remind_at, message, all_day, kind, "
            "repeat_rule, repeat_days FROM reminders "
            "WHERE fired = 0 AND remind_at <= ? ORDER BY remind_at ASC",
            (clock.now() if now is None else now,),
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [dict(r) for r in rows]


def mark_fired(reminder_id: int) -> None:
    """This one has been delivered.

    For a one-off that means finished. For a repeating thing it means **move to
    the next occurrence** — the row is the class, not one instance of it, so
    Monday's lecture becoming next Monday's is an update rather than a new row
    and a dead one. Fifty rows for a term of classes would all have to be
    rewritten the moment the timetable changed.
    """
    conn = store.connect()
    if conn is None:
        return
    try:
        row = conn.execute(
            "SELECT due, remind_at, repeat_rule, repeat_days FROM reminders "
            "WHERE id = ?", (int(reminder_id),)).fetchone()
        rule = (row["repeat_rule"] if row else "") or ""
        if rule:
            days = [int(d) for d in (row["repeat_days"] or "").split(",") if d.strip()]
            nxt = clock.next_occurrence(row["due"], rule, days)
            if nxt:
                # The warning keeps its distance from the thing it warns about.
                lead = row["due"] - row["remind_at"]
                conn.execute(
                    "UPDATE reminders SET due = ?, remind_at = ?, fired = 0 "
                    "WHERE id = ?",
                    (nxt, nxt - lead, int(reminder_id)))
                conn.commit()
                return
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


def match(fragment: str, limit: int = 5) -> list[dict]:
    """Upcoming items whose text contains `fragment`. Check-ins excluded.

    A check-in is a question *about* something, so "move the exam" must find the
    exam and not "How's it going with the exam?" — which contains the word and
    is not the thing anyone means.
    """
    conn = store.connect()
    fragment = " ".join((fragment or "").split()).lower()
    if conn is None or not fragment:
        return []
    try:
        rows = conn.execute(
            "SELECT id, due, remind_at, message, all_day, kind, repeat_rule, "
            "repeat_days FROM reminders "
            "WHERE due >= ? AND kind != 'checkin' AND lower(message) LIKE ? "
            "ORDER BY due ASC LIMIT ?",
            (clock.now() - 60, f"%{fragment}%", limit),
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [dict(r) for r in rows]


def move(item_id: int, due: float, all_day: bool | None = None) -> bool:
    """Change when something happens, keeping how far ahead it warns.

    The lead time is a preference about the thing, not a property of the date:
    "warn me the day before" should survive the exam moving. Recomputing it from
    scratch would quietly turn every moved reminder into one with no warning.
    """
    conn = store.connect()
    if conn is None or not due:
        return False
    try:
        row = conn.execute(
            "SELECT due, remind_at, all_day FROM reminders WHERE id = ?",
            (int(item_id),)).fetchone()
        if row is None:
            return False
        lead = max(0.0, (row["due"] or 0) - (row["remind_at"] or 0))
        keep = row["all_day"] if all_day is None else (1 if all_day else 0)
        conn.execute(
            "UPDATE reminders SET due = ?, remind_at = ?, all_day = ?, fired = 0 "
            "WHERE id = ?",
            (float(due), float(due) - lead, keep, int(item_id)))
        # Its check-in was placed relative to the old date and is now nonsense —
        # possibly in the past, possibly after the thing it asks about.
        conn.execute("DELETE FROM reminders WHERE parent = ?", (int(item_id),))
        conn.commit()
        return True
    except Exception:  # noqa: BLE001
        return False


def rename(item_id: int, message: str) -> bool:
    """Change what something is called, leaving its time alone."""
    conn = store.connect()
    message = _clean(message)
    if conn is None or not message:
        return False
    try:
        conn.execute("UPDATE reminders SET message = ? WHERE id = ?",
                     (message, int(item_id)))
        conn.commit()
        return True
    except Exception:  # noqa: BLE001
        return False


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
