"""Who is allowed to talk to Jarvis.

The core can shut down Rohan's PC and it will be reachable from the open
internet, so this is the file that matters most for keeping it his.

The scheme is device pairing:

* Each device — phone, desktop, the PC agent — pairs once and keeps a long-lived
  token. Nothing to remember, nothing to retype, and one device can be revoked
  without disturbing the others.
* Tokens are random, shown exactly once, and **stored only as a hash**. A copy
  of the database is not a set of working keys.
* Pairing a *new* device requires an *existing* one: an authorised device asks
  for a short code, and the new device redeems it within five minutes.

Which leaves the chicken and egg — the first device has nothing to pair from.
`VONDO_PAIR_SECRET` answers that, and it is deliberately a weak-once door: it
works **only while no devices exist at all**. The moment Rohan's phone is paired
the secret stops opening anything, so a leaked config line later is worthless.
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
CODE_TTL = 300.0          # a pairing code is good for five minutes
CODE_DIGITS = 6

PAIR_SECRET = os.getenv("VONDO_PAIR_SECRET", "")

# Live pairing codes: code -> {"expires": float, "issued_by": device_id}.
# Deliberately in memory only. They live five minutes, and a restart cancelling
# every outstanding code is the correct behaviour, not a bug to fix.
_codes: dict[str, dict] = {}


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


def devices() -> list[dict]:
    conn = store.connect()
    if conn is None:
        return []
    rows = conn.execute(
        "SELECT id, name, kind, paired_ts, last_seen, revoked FROM devices ORDER BY paired_ts"
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------

def _purge_expired() -> None:
    now = time.time()
    for code in [c for c, v in _codes.items() if v["expires"] < now]:
        _codes.pop(code, None)


def start_pairing(issued_by: str) -> tuple[str, float]:
    """An authorised device asks for a code to read out to a new one."""
    _purge_expired()
    # secrets.randbelow, not random: this is a credential for five minutes.
    code = f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"
    _codes[code] = {"expires": time.time() + CODE_TTL, "issued_by": issued_by}
    return code, CODE_TTL


def claim(code: str, name: str, kind: str) -> tuple[str, str]:
    """Redeem a pairing code for a device token."""
    _purge_expired()
    code = (code or "").strip()
    entry = _codes.pop(code, None)  # single use, whatever happens next
    if entry is None:
        raise AuthError("that code is wrong or has expired")
    return issue(name, kind)


def bootstrap(secret: str, name: str, kind: str) -> tuple[str, str]:
    """Pair the very first device using the configured secret.

    Refuses once any device exists, so this door closes by itself and stays
    closed. That is the whole security argument for it — do not relax it into
    "the secret always works" without replacing it with something better.
    """
    if not PAIR_SECRET:
        raise AuthError("first-device pairing is not configured on this server")
    if device_count() > 0:
        raise AuthError(
            "a device is already paired — pair from that device instead")
    if not hmac.compare_digest(PAIR_SECRET, (secret or "").strip()):
        raise AuthError("wrong secret")
    return issue(name, kind)
