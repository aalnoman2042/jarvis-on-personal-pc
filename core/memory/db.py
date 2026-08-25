"""Talking to the database, wherever it happens to live.

On Rohan's PC the database is a file and Python's own `sqlite3` opens it. In the
cloud there is no disk to put a file on, so it lives in Turso and is reached
over HTTPS. Both speak SQLite, which is the entire reason Turso was chosen over
Postgres: every query in `store.py`, `facts.py`, `auth.py` and `migrate.py` is
the same on both, and there is one dialect to get right instead of two.

This module is the seam. It hands back something that behaves like a `sqlite3`
connection either way, so nothing above it knows or cares which it got.

The local path is deliberately *untouched* — it is still a plain `sqlite3`
connection, the one already carrying real conversation history. Only the remote
path is new. A shim over both would have been tidier and would have put working
code at risk for no benefit.
"""
from __future__ import annotations

import os
import sqlite3
import threading

from core import config

# Remote database, set in the cloud. Both must be present or the local file wins,
# because a half-configured remote is the kind of thing that silently writes
# Rohan's memory to the wrong place.
TURSO_URL = os.getenv("VONDO_DB_URL", "").strip()
TURSO_TOKEN = os.getenv("VONDO_DB_TOKEN", "").strip()

DB_FILE = os.getenv("VONDO_DB") or os.path.join(config.PROJECT_DIR, "vondo.db")


def using_turso() -> bool:
    return bool(TURSO_URL and TURSO_TOKEN)


def describe() -> str:
    """A line for the logs, with no credential in it."""
    if using_turso():
        return f"turso ({TURSO_URL})"
    return f"file ({DB_FILE})"


# ---------------------------------------------------------------------------
# The remote side, dressed as sqlite3
# ---------------------------------------------------------------------------

class _Cursor:
    """What `conn.execute(...)` returns, with the three things callers use."""

    __slots__ = ("_rows", "rowcount", "lastrowid", "_at")

    def __init__(self, rows: list[dict], rowcount: int, lastrowid: int | None):
        self._rows = rows
        self.rowcount = rowcount
        self.lastrowid = lastrowid
        self._at = 0

    def fetchone(self) -> dict | None:
        if self._at >= len(self._rows):
            return None
        row = self._rows[self._at]
        self._at += 1
        return row

    def fetchall(self) -> list[dict]:
        rest = self._rows[self._at:]
        self._at = len(self._rows)
        return rest

    def __iter__(self):
        return iter(self.fetchall())


class TursoConnection:
    """A libsql client wearing enough of sqlite3's shape to fool our callers.

    Only the surface `store`, `facts`, `auth` and `migrate` actually use is
    implemented. Deliberately not a general-purpose adapter: an incomplete one
    that pretends to be complete is worse than one whose limits are obvious.
    """

    def __init__(self, url: str, token: str) -> None:
        from libsql_client import create_client_sync

        # http(s) is what the sync client speaks; libsql:// is the same host.
        self._client = create_client_sync(
            url=url.replace("libsql://", "https://"), auth_token=token
        )
        self._lock = threading.Lock()

    def execute(self, sql: str, params=()) -> _Cursor:
        with self._lock:
            result = self._client.execute(sql, list(params))
        # asdict() up front, so rows are plain dicts: row["col"] and dict(row)
        # both work, matching what sqlite3.Row gave us.
        rows = [r.asdict() for r in result.rows]
        return _Cursor(rows, result.rows_affected, result.last_insert_rowid)

    def executescript(self, script: str) -> None:
        # No executescript over the wire, so the schema is sent as a batch. Split
        # on semicolons at the end of a line: our DDL has triggers with internal
        # semicolons, and a naive split on every ';' would cut them in half.
        statements = _split_script(script)
        with self._lock:
            for statement in statements:
                self._client.execute(statement)

    def commit(self) -> None:
        """A no-op: every statement over HTTP is its own transaction.

        Kept so callers do not need to know that. They call commit() after a
        write and it is correct in both worlds.
        """

    def close(self) -> None:
        with self._lock:
            self._client.close()


def _split_script(script: str) -> list[str]:
    """Split a schema script into statements, keeping CREATE TRIGGER intact.

    A trigger body contains its own semicolons and ends with `END;`, so a plain
    `script.split(";")` would send half a trigger and get a syntax error. This
    tracks BEGIN/END nesting instead.
    """
    statements: list[str] = []
    current: list[str] = []
    depth = 0
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        upper = stripped.upper()
        if upper.endswith("BEGIN"):
            depth += 1
        elif upper in ("END;", "END") and depth:
            depth -= 1
            if depth == 0:
                statements.append("\n".join(current).rstrip().rstrip(";"))
                current = []
        elif stripped.endswith(";") and depth == 0:
            statements.append("\n".join(current).rstrip().rstrip(";"))
            current = []
    if current:
        leftover = "\n".join(current).strip().rstrip(";")
        if leftover:
            statements.append(leftover)
    return statements


# ---------------------------------------------------------------------------
# What the rest of the package asks for
# ---------------------------------------------------------------------------

def open_connection():
    """A new connection to whichever database this deployment uses.

    Raises on failure — `store.connect()` is the one that decides a broken
    database means "no memory" rather than "no Jarvis".
    """
    if using_turso():
        return TursoConnection(TURSO_URL, TURSO_TOKEN)

    conn = sqlite3.connect(DB_FILE, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
