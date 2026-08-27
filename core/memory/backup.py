"""Getting everything out, and putting it back.

Until now there was no way to do either. Every conversation, every fact, the
diary, the contacts — all of it lived in one hosted database with no export and
no second copy anywhere. The only fallback was `jarvis.history.jsonl`, frozen at
the migration months ago. A lapsed free tier, a lost login or a bad afternoon
and a year of someone's life would be gone.

**A backup you cannot restore is half a backup**, so `restore` exists and is
tested. Writing only the export half is the common mistake and it is discovered
at exactly the wrong moment.

Two rules:

* **Plain JSON, not a database dump.** It has to be readable in ten years by
  something that is not this program — and readable by Rohan, who should be able
  to open the file and see his own sentences rather than a binary blob.
* **Restore never deletes.** It merges: rows that are already there are left
  alone. A restore run twice must not double anything, and a restore onto a
  live database must not throw away what has happened since the backup.
"""
from __future__ import annotations

import json

from core import clock
from core.memory import store

FORMAT = 1

# Everything worth keeping, and the column that makes a row unique. The key is
# what makes restore idempotent: a row whose key is already present is skipped
# rather than inserted again.
TABLES = {
    "messages": ("ts", "brain", "device", "user", "assistant"),
    "facts": ("ts", "fact"),
    "reminders": ("due", "remind_at", "message", "created", "fired", "all_day",
                  "kind", "device", "parent", "repeat_rule", "repeat_days"),
    "contacts": ("name", "phone", "email", "note", "created", "used"),
    "action_log": ("ts", "tool", "args", "result", "ok", "device"),
}

# What identifies a row for the "already there?" check. Deliberately not the id:
# ids are assigned by whichever database wrote them and mean nothing across a
# restore into a different one.
IDENTITY = {
    "messages": ("ts", "user"),
    "facts": ("fact",),
    "reminders": ("due", "message"),
    "contacts": ("name",),
    "action_log": ("ts", "tool"),
}


def gather() -> dict:
    """Everything Jarvis knows, as one plain structure."""
    conn = store.connect()
    out: dict = {
        "format": FORMAT,
        "taken": round(clock.now(), 1),
        "taken_readable": clock.local().isoformat(timespec="seconds"),
        "tables": {},
    }
    if conn is None:
        return out
    for table, columns in TABLES.items():
        try:
            rows = conn.execute(
                f"SELECT {', '.join(columns)} FROM {table}").fetchall()
            out["tables"][table] = [dict(r) for r in rows]
        except Exception:  # noqa: BLE001  (a table that does not exist yet)
            out["tables"][table] = []
    # Devices and push subscriptions are deliberately NOT exported. They are
    # credentials for specific browsers, they are useless on any other machine,
    # and a backup file is a thing people email themselves.
    return out


def as_json() -> str:
    return json.dumps(gather(), indent=1, ensure_ascii=False)


def summary() -> dict:
    """How much there is, for a screen that offers to save it."""
    data = gather()
    return {k: len(v) for k, v in data["tables"].items()}


def restore(payload: dict) -> dict:
    """Put a backup back, without destroying anything already there.

    Merges rather than replaces. Running it twice adds nothing the second time,
    and running it against a live database keeps whatever has happened since —
    a restore that wipes the present to recover the past is a worse accident
    than the one it is fixing.
    """
    conn = store.connect()
    added = {t: 0 for t in TABLES}
    if conn is None or not isinstance(payload, dict):
        return added
    tables = payload.get("tables") or {}

    for table, columns in TABLES.items():
        rows = tables.get(table) or []
        keys = IDENTITY[table]
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                where = " AND ".join(f"{k} = ?" for k in keys)
                found = conn.execute(
                    f"SELECT 1 FROM {table} WHERE {where} LIMIT 1",
                    tuple(row.get(k) for k in keys)).fetchone()
                if found:
                    continue
                cols = [c for c in columns if c in row]
                conn.execute(
                    f"INSERT INTO {table}({', '.join(cols)}) "
                    f"VALUES ({', '.join('?' for _ in cols)})",
                    tuple(row.get(c) for c in cols))
                added[table] += 1
            except Exception:  # noqa: BLE001  (one bad row must not stop the rest)
                continue
    try:
        conn.commit()
    except Exception:  # noqa: BLE001
        pass
    return added
