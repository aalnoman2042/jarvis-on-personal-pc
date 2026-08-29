"""Who is allowed to talk to Jarvis.

The core can shut down Rohan's PC and it is reachable from the open internet, so
this is the file that matters most for keeping it his.

One way in: a four-digit PIN. Type it once on a device and it is exchanged for a
long-lived token that device keeps, so the PIN itself never travels again.

Being clear-eyed about what four digits means: ten thousand possibilities on a
public URL. Unthrottled, a script exhausts that in under a minute. So the PIN is
never the only thing standing there:

  * Wrong guesses are counted per address, and after MAX_TRIES that address is
    locked out for LOCKOUT. Ten thousand guesses at five per fifteen minutes is
    about three weeks of continuous effort from one source.
  * Every attempt costs ATTEMPT_DELAY whether it is right or wrong. Invisible
    when you type it once; it multiplies the cost of a script by thousands. It
    is unconditional on purpose — a delay only on failure would tell an attacker
    which guesses were close to something.
  * The lockout is per address, never global. A global one would let anyone lock
    Rohan out of his own assistant by guessing badly on purpose, which is worse
    than the thing it prevents.

Tokens are random, shown exactly once, and stored only as hashes — a copy of the
database is not a set of working keys.

Six digits would multiply the guessing work by a hundred for two extra
keypresses. Change VONDO_PIN and nothing else needs touching.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
import uuid

from core.memory import store

TOKEN_BYTES = 32

PIN = os.getenv("VONDO_PIN", "").strip()

MAX_TRIES = 5
LOCKOUT = 900.0        # 15 minutes
ATTEMPT_DELAY = 0.4    # seconds, paid by every attempt

# address -> [failure timestamps]. In memory on purpose: a restart clearing
# lockouts is acceptable, and it keeps failed guesses out of the database.
_failures: dict[str, list[float]] = {}


class AuthError(Exception):
    """Rejected. The message is safe to show a caller."""


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def device_count() -> int:
    conn = store.connect()
    if conn is None:
        return 0
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM devices WHERE revoked = 0"
        ).fetchone()["n"]
    except Exception:  # noqa: BLE001
        return 0


def issue(name: str, kind: str) -> tuple[str, str]:
    """Create a device and return (device_id, token). The token is shown once."""
    conn = store.connect()
    if conn is None:
        raise AuthError("storage unavailable")
    device_id = uuid.uuid4().hex
    token = secrets.token_urlsafe(TOKEN_BYTES)
    now = time.time()
    conn.execute(
        "INSERT INTO devices(id, name, kind, token_hash, paired_ts, last_seen, revoked) "
        "VALUES (?,?,?,?,?,?,0)",
        (device_id, (name or "device")[:60], (kind or "client")[:20],
         _hash(token), now, now),
    )
    conn.commit()
    return device_id, token


def identify(token: str) -> dict:
    """Return the device this token belongs to, or raise AuthError.

    Compared against every stored hash with a constant-time check. There are a
    handful of devices, so the linear scan is free — and it avoids leaking which
    tokens exist through timing.
    """
    token = (token or "").strip()
    if not token:
        raise AuthError("no token")
    conn = store.connect()
    if conn is None:
        raise AuthError("storage unavailable")
    wanted = _hash(token)
    try:
        rows = conn.execute(
            "SELECT id, name, kind, token_hash FROM devices WHERE revoked = 0"
        ).fetchall()
    except Exception:  # noqa: BLE001
        raise AuthError("storage unavailable") from None
    for row in rows:
        if hmac.compare_digest(row["token_hash"], wanted):
            try:
                conn.execute("UPDATE devices SET last_seen = ? WHERE id = ?",
                             (time.time(), row["id"]))
                conn.commit()
            except Exception:  # noqa: BLE001  (last_seen is a nicety, not a gate)
                pass
            return {"id": row["id"], "name": row["name"], "kind": row["kind"]}
    raise AuthError("unknown or revoked token")


def revoke(device_id: str) -> bool:
    conn = store.connect()
    if conn is None:
        return False
    cur = conn.execute("UPDATE devices SET revoked = 1 WHERE id = ?", (device_id,))
    conn.commit()
    return bool(cur.rowcount)


def rename(device_id: str, name: str) -> bool:
    """Give a device a name a person would recognise.

    Auto-generated names collide — two phones in the same browser produce the
    same string — and a list you cannot tell apart is a list you should not be
    revoking from.
    """
    conn = store.connect()
    name = " ".join((name or "").split())[:40]
    if conn is None or not name:
        return False
    cur = conn.execute("UPDATE devices SET name = ? WHERE id = ?", (name, device_id))
    conn.commit()
    return bool(cur.rowcount)


def devices() -> list[dict]:
    conn = store.connect()
    if conn is None:
        return []
    rows = conn.execute(
        "SELECT id, name, kind, paired_ts, last_seen, revoked FROM devices "
        "ORDER BY paired_ts"
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# The PIN
# ---------------------------------------------------------------------------

def _recent_failures(ip: str) -> list[float]:
    now = time.time()
    kept = [t for t in _failures.get(ip, []) if now - t < LOCKOUT]
    if kept:
        _failures[ip] = kept
    else:
        _failures.pop(ip, None)
    return kept


def locked_for(ip: str) -> float:
    """Seconds until this address may try again. 0 if it may try now."""
    failures = _recent_failures(ip)
    if len(failures) < MAX_TRIES:
        return 0.0
    return max(0.0, LOCKOUT - (time.time() - failures[0]))


def login(pin: str, name: str, kind: str, ip: str = "") -> tuple[str, str]:
    """Exchange the PIN for a device token.

    Raises AuthError with something worth showing a person — including how long
    a lockout has left, because "wrong PIN" when you are actually locked out is
    the kind of message that makes people retype a correct PIN twenty times.
    """
    if not PIN:
        raise AuthError("No PIN is set on this server.")

    waiting = locked_for(ip)
    if waiting > 0:
        minutes = max(1, int(waiting // 60))
        raise AuthError(f"Too many wrong tries. Try again in {minutes} minute"
                        f"{'s' if minutes > 1 else ''}.")

    time.sleep(ATTEMPT_DELAY)

    if not hmac.compare_digest(PIN, (pin or "").strip()):
        _failures.setdefault(ip, []).append(time.time())
        left = MAX_TRIES - len(_recent_failures(ip))
        if left <= 0:
            raise AuthError("Too many wrong tries. Locked for 15 minutes.")
        raise AuthError(f"Wrong PIN. {left} attempt{'s' if left > 1 else ''} left.")

    _failures.pop(ip, None)     # a correct PIN wipes the slate for this address
    return issue(name, kind)
