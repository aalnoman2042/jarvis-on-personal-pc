"""Getting a reminder from the database to Rohan.

The diary lives in `core.memory.agenda` and is the same on every device. This is
the part that notices something has come due and says so.

**A reminder is only marked delivered if somebody was actually told.** That one
rule is the difference between this and the version it replaces. Sweeping on a
timer and marking everything fired would mean a free-tier server, waking up at
some arbitrary moment with nobody connected, quietly consuming the exam warning
and going back to sleep. So an undelivered item stays pending, and the next
client to open the app gets it at once — late, and labelled as late, which is
worth infinitely more than silent.

**Delivery today is to whoever has the app open**, over the websocket they
already hold. That covers the case that matters most — the phone in his hand —
and it needs no Firebase account, no VAPID keys and no third party. Waking a
closed app is push, and push is the next piece of work; the shape here does not
change when it arrives, because it is already "try every channel, mark fired if
one of them worked".
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from starlette.concurrency import run_in_threadpool

from core import reminders

log = logging.getLogger("vondo.nudges")

# How often to look. Reminders are minutes-grained, not seconds-grained, and in
# the cloud each look is a query against a database over the network.
INTERVAL = 30.0


class Listeners:
    """The HUD sockets currently open. Usually one; occasionally two."""

    def __init__(self) -> None:
        self._sockets: set = set()

    def add(self, websocket) -> None:
        self._sockets.add(websocket)

    def remove(self, websocket) -> None:
        self._sockets.discard(websocket)

    def count(self) -> int:
        return len(self._sockets)

    async def send(self, frame: dict) -> int:
        """Push a frame to everyone listening. Returns how many actually took it.

        A socket that fails is dropped rather than retried: it is gone, and the
        count it does not contribute to is exactly what decides whether the
        reminder stays pending.
        """
        payload = json.dumps(frame)
        delivered = 0
        for socket in list(self._sockets):
            try:
                await socket.send_text(payload)
                delivered += 1
            except Exception:  # noqa: BLE001  (closed mid-send; nothing to salvage)
                self._sockets.discard(socket)
        return delivered


listeners = Listeners()


def _frame(item: dict) -> dict:
    return {
        "type": "reminder",
        "id": item["id"],
        "text": reminders.wording(item),
        "message": item["message"],
        "due": item["due"],
        "all_day": bool(item.get("all_day")),
    }


async def deliver_due() -> int:
    """Send anything that has come due. Returns how many were delivered.

    Safe to call as often as you like: `agenda.ready()` only returns what has
    not been marked, so a burst of calls delivers each item once.
    """
    items = await run_in_threadpool(reminders.due)
    if not items:
        return 0
    sent = 0
    for item in items:
        if await listeners.send(_frame(item)):
            await run_in_threadpool(reminders.delivered, item["id"])
            sent += 1
            log.info("reminder delivered: %s", item["message"][:60])
    if len(items) > sent:
        log.info("%d reminder(s) waiting for someone to be listening", len(items) - sent)
    return sent


async def loop(stop: asyncio.Event) -> None:
    """Watch the diary for as long as the server is up."""
    while not stop.is_set():
        try:
            await deliver_due()
        except Exception:  # noqa: BLE001  (a bad row must not end the loop)
            log.exception("reminder sweep failed")
        # Waiting on the event rather than sleeping means shutdown is immediate
        # instead of taking up to a full interval.
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=INTERVAL)
