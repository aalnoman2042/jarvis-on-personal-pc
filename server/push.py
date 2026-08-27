"""Web Push — reminders that arrive with the app closed.

The Android build held its own alarms, so a closed app was never a problem
there. A PWA cannot do that: it has no process, no alarms, and no way to wake
itself. Without push, a reminder can only arrive while the tab is open, which
is precisely when you least need telling.

**This needs no Firebase and no account.** That is worth stating plainly
because the usual advice says otherwise. Chrome's push service does sit on
Google infrastructure, but the Web Push protocol is open: a VAPID key pair is
generated here, the browser hands out an endpoint of its own accord, and the
server posts an encrypted payload to it. Nothing is registered with anybody.

**The keys are generated once and kept in the database.** Putting them in the
environment would mean Rohan pasting a private key into a dashboard, and a
rotated key silently invalidates every existing subscription — so they live
where the subscriptions live, and the two can never disagree.

Same delivery contract as everything else here: a subscription that fails
permanently is removed, and nothing is marked delivered on the strength of a
send. See nudges.py for why that distinction is the whole subsystem.
"""
from __future__ import annotations

import json
import logging

from core.memory import store

log = logging.getLogger("vondo.push")

# Where the keys and subscriptions live. `settings` already exists for exactly
# this kind of thing: small, singular, and needing to outlive a restart.
_VAPID_PRIVATE = "vapid_private"
_VAPID_PUBLIC = "vapid_public"
_SUBS = "push_subscriptions"

# Nobody is reachable at a subscription the browser has forgotten. These are
# the codes that mean "gone for good" rather than "try again later".
DEAD = (404, 410)


def _get(key: str, default: str = "") -> str:
    conn = store.connect()
    if conn is None:
        return default
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    except Exception:  # noqa: BLE001
        return default
    return row["value"] if row else default


def _put(key: str, value: str) -> None:
    conn = store.connect()
    if conn is None:
        return
    try:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value))
        conn.commit()
    except Exception:  # noqa: BLE001
        pass


def keys() -> tuple[str, str]:
    """The VAPID pair, generated on first use and kept for good.

    Regenerating these silently invalidates every subscription already handed
    out — the browser signed up against a specific public key — so they are
    created exactly once and never touched again.
    """
    private, public = _get(_VAPID_PRIVATE), _get(_VAPID_PUBLIC)
    if private and public:
        return private, public
    try:
        from py_vapid import Vapid01
        import base64

        vapid = Vapid01()
        vapid.generate_keys()
        private = base64.urlsafe_b64encode(
            vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
        ).decode().rstrip("=")
        raw = vapid.public_key.public_bytes_raw() if hasattr(vapid.public_key, "public_bytes_raw") else None
        if raw is None:  # older cryptography
            from cryptography.hazmat.primitives import serialization
            raw = vapid.public_key.public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint)
        public = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        _put(_VAPID_PRIVATE, private)
        _put(_VAPID_PUBLIC, public)
        log.info("generated a VAPID key pair")
    except Exception as exc:  # noqa: BLE001
        log.warning("could not generate VAPID keys: %s", exc)
        return "", ""
    return private, public


def public_key() -> str:
    return keys()[1]


def available() -> bool:
    try:
        import pywebpush  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return bool(public_key())


# ---------------------------------------------------------------------------
# Who is subscribed
# ---------------------------------------------------------------------------

def _load() -> list[dict]:
    try:
        return json.loads(_get(_SUBS, "[]")) or []
    except Exception:  # noqa: BLE001
        return []


def _save(subs: list[dict]) -> None:
    _put(_SUBS, json.dumps(subs[:20]))   # a person does not have twenty devices


def subscribe(subscription: dict, device: str = "") -> bool:
    """Remember a browser's push endpoint. Replaces any earlier one for it."""
    endpoint = (subscription or {}).get("endpoint", "")
    if not endpoint:
        return False
    subs = [s for s in _load() if s.get("endpoint") != endpoint]
    subs.append({"endpoint": endpoint,
                 "keys": subscription.get("keys", {}),
                 "device": device})
    _save(subs)
    log.info("push subscription stored (%d total)", len(subs))
    return True


def unsubscribe(endpoint: str) -> None:
    _save([s for s in _load() if s.get("endpoint") != endpoint])


def count() -> int:
    return len(_load())


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send(payload: dict) -> int:
    """Push to every subscribed browser. Returns how many were accepted.

    Blocking — call it in a thread. A dead subscription is dropped rather than
    retried for ever: the browser has forgotten it, and no amount of asking
    changes that.
    """
    if not available():
        return 0
    subs = _load()
    if not subs:
        return 0

    from pywebpush import webpush, WebPushException

    private = keys()[0]
    body = json.dumps(payload)
    sent = 0
    alive: list[dict] = []
    for sub in subs:
        try:
            webpush(
                subscription_info={"endpoint": sub["endpoint"], "keys": sub.get("keys", {})},
                data=body,
                vapid_private_key=private,
                # A contact address is required by the protocol so a push
                # service can reach whoever is sending. mailto: with the owner's
                # address is the whole requirement.
                vapid_claims={"sub": "mailto:jarvis@vondo.local"},
                timeout=10,
            )
            sent += 1
            alive.append(sub)
        except WebPushException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", 0)
            if code in DEAD:
                log.info("dropping a subscription the browser has forgotten")
                continue          # gone for good; do not keep it
            alive.append(sub)     # transient — keep and try again next time
            log.warning("push failed (%s)", code or exc)
        except Exception as exc:  # noqa: BLE001
            alive.append(sub)
            log.warning("push error: %s", exc)
    if len(alive) != len(subs):
        _save(alive)
    return sent
