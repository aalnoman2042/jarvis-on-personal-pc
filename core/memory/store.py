"""Where Jarvis keeps what was said — one SQLite file.

Replaces the append-only `jarvis.history.jsonl`. That file was fine for one
process on one machine, but v2 has a phone and a desktop talking to the same
brain, and two appenders to one text file is how you lose a line. SQLite gives
us atomic writes, real concurrency and search, in a single file that is still
trivially easy to back up or carry away.

Design notes worth keeping:

* **WAL mode.** Readers never block the writer and the writer never blocks
  readers, which is exactly the shape of the cloud core: many small reads while
  one turn is being recorded.
* **A connection per thread.** sqlite3 objects are not safe to share across
  threads, and Jarvis has a reminder thread, a UI thread and (soon) a websocket
  loop. `threading.local` is cheaper and less error-prone than a lock.
* **Nothing here may raise into a conversation.** Memory failing is annoying;
  memory taking Jarvis down with it is not acceptable. Every public function
  swallows storage errors and degrades to "no memory", the same contract the
  file-based version had.
* **Retention is forever.** Chosen deliberately: years of conversation is a few
  megabytes, and remembering is the point. What gets *sent* to a model each turn
  is trimmed separately — see `as_openai` in this package's `__init__`. Storage
  and context are different decisions and must not be conflated again.
"""
from __future__ import annotations

import sqlite3
import threading
import time

from core import config
from core.memory import db

# Where the database lives is decided in db.py: a file on Rohan's PC, Turso in
# the cloud. Re-exported because callers and logs still ask for it by this name.
DB_FILE = db.DB_FILE

MAX_TEXT = 1000          # characters stored per message
SCHEMA_VERSION = 1

_local = threading.local()
_init_lock = threading.Lock()
_initialised = False

# --- schema ---------------------------------------------------------------
#
# `device` and the devices/reminders/settings tables are unused today. They are
# here because adding a column to an empty schema costs nothing, while migrating
# a live one later costs a phase. Phases 02 and 03 fill them in.

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id        INTEGER PRIMARY KEY,
    ts        REAL NOT NULL,
    brain     TEXT NOT NULL DEFAULT '',
    device    TEXT NOT NULL DEFAULT '',
    user      TEXT NOT NULL,
    assistant TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_ts ON messages(ts);

CREATE TABLE IF NOT EXISTS facts (
    id   INTEGER PRIMARY KEY,
    ts   REAL NOT NULL,
    fact TEXT NOT NULL COLLATE NOCASE UNIQUE
);

CREATE TABLE IF NOT EXISTS action_log (
    id     INTEGER PRIMARY KEY,
    ts     REAL NOT NULL,
    tool   TEXT NOT NULL,
    args   TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '',
    ok     INTEGER NOT NULL DEFAULT 1,
    device TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS action_log_ts ON action_log(ts);

CREATE TABLE IF NOT EXISTS devices (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL DEFAULT '',
    token_hash TEXT NOT NULL DEFAULT '',
    paired_ts  REAL,
    last_seen  REAL,
    revoked    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reminders (
    id      INTEGER PRIMARY KEY,
    due     REAL NOT NULL,
    message TEXT NOT NULL,
    created REAL NOT NULL,
    fired   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Full-text search over the conversation, so "what did I say about the deadline"
# retrieves instead of hoping it is still inside the last dozen turns. The
# external-content form stores no second copy of the text; the triggers keep the
# index honest when rows are added or removed.
_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    user, assistant, content='messages', content_rowid='id', tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, user, assistant)
    VALUES (new.id, new.user, new.assistant);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, user, assistant)
    VALUES ('delete', old.id, old.user, old.assistant);
END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, user, assistant)
    VALUES ('delete', old.id, old.user, old.assistant);
    INSERT INTO messages_fts(rowid, user, assistant)
    VALUES (new.id, new.user, new.assistant);
END;
"""

has_search = True  # flipped off below if this SQLite build lacks FTS5


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def connect() -> sqlite3.Connection | None:
    """This thread's connection, creating the schema on first use.

    Returns None when memory is switched off or the database cannot be opened —
    callers treat that exactly like "nothing remembered yet".
    """
    if not config.MEMORY_ENABLED:
        return None
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    try:
        conn = db.open_connection()
        _ensure_schema(conn)
    except Exception:  # noqa: BLE001  (disk full, locked, unreachable — keep talking)
        return None
    _local.conn = conn
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables once per process. Cheap and idempotent afterwards."""
    global _initialised, has_search
    with _init_lock:
        conn.executescript(_SCHEMA)
        try:
            conn.executescript(_FTS)
        except Exception:  # noqa: BLE001
            # Some SQLite builds ship without FTS5, and Turso raises its own
            # error type rather than sqlite3's — catching only sqlite3's would
            # have turned a missing feature into a dead server.
            has_search = False
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
        if not _initialised:
            _initialised = True
            from core.memory import migrate  # late: migrate imports this module
            migrate.run(conn)


def meta_get(key: str, default: str = "") -> str:
    conn = connect()
    if conn is None:
        return default
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    except Exception:  # noqa: BLE001
        return default
    return row["value"] if row else default


def meta_set(key: str, value: str) -> None:
    conn = connect()
    if conn is None:
        return
    try:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        conn.commit()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# The conversation
# ---------------------------------------------------------------------------

def add_turn(user: str, assistant: str, brain: str = "", device: str = "") -> None:
    """Record one finished exchange. Never raises — memory must not break Jarvis."""
    user, assistant = (user or "").strip(), (assistant or "").strip()
    if not user or not assistant:
        return
    conn = connect()
    if conn is None:
        return
    try:
        conn.execute(
            "INSERT INTO messages(ts, brain, device, user, assistant) VALUES (?,?,?,?,?)",
            (round(time.time(), 1), brain or "", device or "",
             user[:MAX_TEXT], assistant[:MAX_TEXT]),
        )
        conn.commit()
    except Exception:  # noqa: BLE001
        pass


def recent(limit: int | None = None) -> list[dict]:
    """The most recent exchanges, oldest last — same shape the JSONL returned."""
    conn = connect()
    if conn is None:
        return []
    if limit is not None and limit <= 0:
        return []
    try:
        if limit is None:
            rows = conn.execute(
                "SELECT ts, brain, user, assistant FROM messages ORDER BY id"
            ).fetchall()
        else:
            # Newest N by id, then flipped, so callers still read oldest-first.
            rows = conn.execute(
                "SELECT ts, brain, user, assistant FROM messages "
                "ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()[::-1]
    except Exception:  # noqa: BLE001
        return []
    return [dict(r) for r in rows]


def search(query: str, limit: int = 10) -> list[dict]:
    """Find past exchanges by words in them, best matches first.

    This is the thing the flat file could never do: reach past the rolling
    window into everything ever said.
    """
    query = (query or "").strip()
    conn = connect()
    if conn is None or not query or not has_search:
        return []
    try:
        rows = conn.execute(
            "SELECT m.ts, m.brain, m.user, m.assistant "
            "FROM messages_fts f JOIN messages m ON m.id = f.rowid "
            "WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()
    except Exception:  # noqa: BLE001  (FTS5 rejects some punctuation as a query)
        return []
    return [dict(r) for r in rows]


def count() -> int:
    conn = connect()
    if conn is None:
        return 0
    try:
        return conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
    except Exception:  # noqa: BLE001
        return 0


def clear() -> None:
    """Forget the conversation. Facts and the action log are left alone."""
    conn = connect()
    if conn is None:
        return
    try:
        conn.execute("DELETE FROM messages")
        conn.commit()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# What Jarvis actually did
#
# New in v2. The HUD shows tool calls as system lines ("opened chrome"), and
# "what did you do yesterday?" should be answerable. Written from one place —
# the dispatcher in core/tools/llm_tools.py — so no brain has to remember to.
# ---------------------------------------------------------------------------

def log_action(tool: str, args: str = "", result: str = "",
               ok: bool = True, device: str = "") -> None:
    """Record one tool call. Never raises."""
    conn = connect()
    if conn is None or not tool:
        return
    try:
        conn.execute(
            "INSERT INTO action_log(ts, tool, args, result, ok, device) VALUES (?,?,?,?,?,?)",
            (round(time.time(), 1), tool, (args or "")[:MAX_TEXT],
             (result or "")[:MAX_TEXT], 1 if ok else 0, device or ""),
        )
        conn.commit()
    except Exception:  # noqa: BLE001
        pass


def recent_actions(limit: int = 20) -> list[dict]:
    """The last things Jarvis did, newest first."""
    conn = connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT ts, tool, args, result, ok, device FROM action_log "
            "ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [dict(r) for r in rows]
