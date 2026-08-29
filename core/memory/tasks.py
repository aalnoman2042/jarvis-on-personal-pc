"""Things to do, as opposed to things that happen.

The diary holds what happens at a time: a class, an exam, a train. This holds
what has to get done, which is a different shape and is why it is a different
table — a task has no required date and does have a finished state, and those
two differences are the whole distinction.

Without it there was nowhere to put "write the methodology section". Said to
Jarvis, it either became a reminder at an invented time or was lost, and
"what should I work on now?" had nothing to answer from.

**`source` separates what was asked for from what was noticed.** When Rohan
says "add a task", that is an instruction. When he says "I need to finish the
draft this week", that is Jarvis inferring — a guess, and it has to be raised as
one. Treating the two identically is how an assistant starts nagging about
things nobody actually committed to.

Same contract as the rest of the package: nothing here raises into a
conversation.
"""
from __future__ import annotations

from core import clock
from core.memory import store

MAX_TEXT = 300

# 2 high, 1 normal, 0 someday. Three is enough — a five-point scale is a thing
# people spend time adjusting rather than doing.
HIGH, NORMAL, LOW = 2, 1, 0

_WORDS = {HIGH: "high", NORMAL: "", LOW: "someday"}


def _clean(text: str) -> str:
    return " ".join((text or "").split())[:MAX_TEXT]


def add(text: str, priority: int = NORMAL, due: float = 0.0,
        minutes: int = 0, tag: str = "", source: str = "asked") -> int | None:
    """Put something on the list. Returns its id."""
    conn = store.connect()
    text = _clean(text)
    if conn is None or not text:
        return None
    try:
        # The same thing said twice is one task. Someone repeating themselves is
        # emphasis, not a second job.
        existing = conn.execute(
            "SELECT id FROM tasks WHERE done = 0 AND lower(text) = ? LIMIT 1",
            (text.lower(),)).fetchone()
        if existing:
            # Everything that was actually given, not just the priority. This
            # used to update priority alone and silently drop a new deadline —
            # so "the methodology is due Sunday now" was answered with "On the
            # list, due Sunday" while the row kept its old date. A confirmation
            # of something that did not happen is worse than a refusal.
            sets, values = [], []
            if priority != NORMAL:
                sets.append("priority = ?")
                values.append(int(priority))
            if due:
                sets.append("due = ?")
                values.append(float(due))
            if minutes:
                sets.append("minutes = ?")
                values.append(int(minutes))
            if sets:
                values.append(existing["id"])
                conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?",
                             tuple(values))
                conn.commit()
            return int(existing["id"])
        cursor = conn.execute(
            "INSERT INTO tasks(text, created, priority, due, minutes, tag, source) "
            "VALUES (?,?,?,?,?,?,?)",
            (text, round(clock.now(), 1), int(priority), float(due or 0),
             int(minutes or 0), _clean(tag)[:40], source))
        conn.commit()
        return cursor.lastrowid
    except Exception:  # noqa: BLE001
        return None


def open_tasks(limit: int = 30) -> list[dict]:
    """What is still to do, most pressing first.

    Ordered by deadline before priority: a normal thing due tomorrow beats an
    important thing with no date, because the deadline is the part that will
    stop being possible.
    """
    conn = store.connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE done = 0 "
            # A due date of 0 means none, and must sort last rather than first.
            "ORDER BY CASE WHEN due > 0 THEN due ELSE 1e12 END ASC, "
            "priority DESC, created ASC LIMIT ?",
            (limit,)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [dict(r) for r in rows]


def find(fragment: str) -> list[dict]:
    conn = store.connect()
    fragment = _clean(fragment).lower()
    if conn is None or not fragment:
        return []
    try:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE done = 0 AND lower(text) LIKE ? "
            "ORDER BY created ASC LIMIT 5", (f"%{fragment}%",)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [dict(r) for r in rows]


def finish(task_id: int) -> bool:
    """Mark it done. Kept, not deleted — what got done is worth knowing."""
    conn = store.connect()
    if conn is None:
        return False
    try:
        conn.execute("UPDATE tasks SET done = 1, done_at = ? WHERE id = ?",
                     (round(clock.now(), 1), int(task_id)))
        conn.commit()
        return True
    except Exception:  # noqa: BLE001
        return False


def reopen(task_id: int) -> bool:
    conn = store.connect()
    if conn is None:
        return False
    try:
        conn.execute("UPDATE tasks SET done = 0, done_at = 0 WHERE id = ?",
                     (int(task_id),))
        conn.commit()
        return True
    except Exception:  # noqa: BLE001
        return False


def drop(task_id: int) -> bool:
    conn = store.connect()
    if conn is None:
        return False
    try:
        cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (int(task_id),))
        conn.commit()
        return bool(cursor.rowcount)
    except Exception:  # noqa: BLE001
        return False


def reschedule(task_id: int, due: float) -> bool:
    """Move a deadline. `due` of 0 removes it.

    The only ways out of an overdue task used to be finishing it or deleting
    it, so anything that slipped was nagged about for ever — which is how a
    briefing stops being read. A deadline that can move is what makes an
    honest one worth setting.

    `moved` counts how often. A task that has been pushed four times is telling
    you something a fifth date will not fix.
    """
    conn = store.connect()
    if conn is None:
        return False
    try:
        cursor = conn.execute(
            "UPDATE tasks SET due = ?, moved = moved + 1 WHERE id = ? AND done = 0",
            (float(due or 0), int(task_id)))
        conn.commit()
        return bool(cursor.rowcount)
    except Exception:  # noqa: BLE001
        return False


def done_since(since: float) -> list[dict]:
    """What was finished recently — for a weekly look back."""
    conn = store.connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE done = 1 AND done_at >= ? "
            "ORDER BY done_at DESC LIMIT 50", (float(since),)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [dict(r) for r in rows]


def noticed_to_chase(older_than: float = 2 * 86400.0, limit: int = 3) -> list[dict]:
    """Commitments Jarvis inferred, old enough to ask about, not yet asked.

    Only `source='noticed'` — things Rohan said he would do, which Jarvis
    recorded on its own rather than being told to. Those are a guess and have to
    be raised as one; something he explicitly put on the list does not need
    chasing, it needs doing.

    `asked_at` is why this asks ONCE. Chasing the same commitment every morning
    is how a helpful assistant becomes a thing you close.
    """
    conn = store.connect()
    if conn is None:
        return []
    cutoff = clock.now() - older_than
    try:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE done = 0 AND source = 'noticed' "
            "AND created <= ? AND asked_at = 0 "
            "ORDER BY created ASC LIMIT ?", (cutoff, limit)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [dict(r) for r in rows]


def mark_asked(task_id: int) -> None:
    """Note that it has been raised, so it is not raised again."""
    conn = store.connect()
    if conn is None:
        return
    try:
        conn.execute("UPDATE tasks SET asked_at = ? WHERE id = ?",
                     (round(clock.now(), 1), int(task_id)))
        conn.commit()
    except Exception:  # noqa: BLE001
        pass


def counts() -> dict:
    conn = store.connect()
    empty = {"open": 0, "overdue": 0, "high": 0}
    if conn is None:
        return empty
    try:
        now = clock.now()
        row = conn.execute(
            "SELECT COUNT(*) AS open_n, "
            "SUM(CASE WHEN due > 0 AND due < ? THEN 1 ELSE 0 END) AS overdue_n, "
            "SUM(CASE WHEN priority = 2 THEN 1 ELSE 0 END) AS high_n "
            "FROM tasks WHERE done = 0", (now,)).fetchone()
    except Exception:  # noqa: BLE001
        return empty
    if not row:
        return empty
    return {"open": int(row["open_n"] or 0),
            "overdue": int(row["overdue_n"] or 0),
            "high": int(row["high_n"] or 0)}


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------

def describe(task: dict, base: float | None = None) -> str:
    bits = [task["text"]]
    mark = _WORDS.get(int(task.get("priority", NORMAL)), "")
    if mark:
        bits.append(f"({mark})")
    if task.get("due"):
        when = clock.say(task["due"], False, base)
        overdue = task["due"] < (clock.now() if base is None else base)
        bits.append(f"— {'overdue, was ' if overdue else 'due '}{when}")
    # Said out loud from the third slip. Once is life; repeatedly is the task
    # being wrong rather than the date, and that is worth noticing out loud
    # rather than quietly moving it a fourth time.
    if int(task.get("moved") or 0) >= 3:
        bits.append(f"(moved {int(task['moved'])} times)")
    return " ".join(bits)


def block(limit: int = 8) -> str:
    """The open list, for the system prompt."""
    items = open_tasks(limit)
    if not items:
        return ""
    lines = "\n".join(f"- {describe(t)}" for t in items)
    return ("\n\nStill to do (mention only if relevant or asked; use "
            "finish_task when they say something is done):\n" + lines)
