"""Carry v1's memory into the database, once.

Runs automatically the first time the database is opened. Two rules make this
safe to leave switched on forever:

* **It never touches the original files.** `jarvis.history.jsonl` and
  `jarvis.facts.json` stay exactly where they are, readable in a text editor.
  If the database ever disappoints, the whole history is still sitting there.
  Nothing writes to them any more; they are frozen, not deleted.
* **It runs once.** A marker in the `meta` table records that the import
  happened, so clearing the conversation later does not resurrect it.
"""
from __future__ import annotations

import json
import os
import time

from core import config

HISTORY_FILE = os.path.join(config.PROJECT_DIR, "jarvis.history.jsonl")
FACTS_FILE = os.path.join(config.PROJECT_DIR, "jarvis.facts.json")

MARKER = "migrated_from_files"


def _turns_from_jsonl(path: str) -> list[dict]:
    """Read the v1 history. Skips unreadable lines rather than giving up.

    A half-written line — two copies of Jarvis running, or a power cut mid-write
    — costs exactly that one exchange. This is why v1 stored one JSON object per
    line rather than a single document, and it is why the import can be trusted.
    """
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:  # noqa: BLE001  (malformed line — skip just it)
                    continue
                if isinstance(rec, dict) and rec.get("user") and rec.get("assistant"):
                    out.append(rec)
    except OSError:
        return []
    return out


def _facts_from_json(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001  (missing or corrupt — nothing to carry)
        return []
    if not isinstance(data, list):
        return []
    return [str(x).strip() for x in data if str(x).strip()]


def run(conn) -> str:
    """Import the v1 files if this has never been done. Returns what happened.

    Takes the connection rather than calling store.connect(), because it is
    invoked from inside schema setup — asking for a connection there would
    recurse.
    """
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (MARKER,)).fetchone()
        if row:
            return "already migrated"

        turns = _turns_from_jsonl(HISTORY_FILE)
        for rec in turns:
            conn.execute(
                "INSERT INTO messages(ts, brain, device, user, assistant) VALUES (?,?,?,?,?)",
                (float(rec.get("ts") or 0.0), str(rec.get("brain") or ""), "",
                 str(rec["user"])[:1000], str(rec["assistant"])[:1000]),
            )

        known = _facts_from_json(FACTS_FILE)
        for fact in known:
            conn.execute(
                "INSERT OR IGNORE INTO facts(ts, fact) VALUES (?, ?)",
                (round(time.time(), 1), fact),
            )

        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (MARKER, f"{time.time():.0f}:{len(turns)} turns,{len(known)} facts"),
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001  (never block startup over a migration)
        return f"skipped ({exc})"

    if not turns and not known:
        return "nothing to migrate"
    return f"imported {len(turns)} exchanges and {len(known)} facts"
