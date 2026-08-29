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
from server import push

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


# When the archive is fully indexed there is nothing to do, and looking anyway
# is two full scans over the network every thirty seconds, for ever. So a pass
# that finds nothing waits this long before looking again. New turns are the
# only thing that can create work, and being a few minutes behind on embedding
# one is invisible — `recent()` already puts it in front of the model.
IDLE_GAP = 300.0

# A refused-for-quota pass waits longer than an idle one, but NOT as long as
# brain_fallback's half hour. The two are different limits: a brain's free tier
# is daily, and an embedding one is measured per minute — observed recovering
# within a few minutes of being exhausted by a burst. Half an hour would leave
# a backlog sitting for twenty-nine minutes it did not need to. Ten is long
# enough that a genuinely daily cap costs a handful of refused calls, which cost
# nothing but a log line.
QUOTA_GAP = 600.0
_next_catch_up = 0.0


async def catch_up(force: bool = False) -> int:
    """Give meaning-based recall a little more of the archive to work with.

    Deliberately here and not on the write path. Embedding inside `add_turn`
    would make storing a sentence wait on Google, and would turn an embedding
    outage into a memory outage; doing it in the sweep costs a turn nothing and
    an interruption only means the index is a few rows behind for a while.

    One small batch per pass, in a worker thread because it is a blocking HTTP
    call and this loop shares an event loop with the sockets.
    """
    global _next_catch_up
    from core import clock
    from core.memory import vectors

    now = clock.now()
    if not force and now < _next_catch_up:
        return 0
    if not vectors.available():
        # No key, no numpy, no quota. Nothing here will start working in the
        # next half minute, so stop asking every half minute.
        _next_catch_up = now + IDLE_GAP
        return 0
    done = await run_in_threadpool(vectors.backfill)
    if done:
        _next_catch_up = 0.0
    else:
        _next_catch_up = now + (QUOTA_GAP if vectors.quota_exhausted() else IDLE_GAP)
    return done


async def deliver_due() -> int:
    """Send anything that has come due. Returns how many were put on the wire.

    **Nothing is marked delivered here.** That is the whole point of this
    function's shape and it was wrong until now.

    `send_text` not raising means the bytes reached a socket buffer, not that a
    person saw anything. A backgrounded Android WebView keeps its TCP connection
    wide open while its JavaScript is frozen — so the frame was accepted, the
    row was marked fired, and the reminder was consumed for ever without ever
    being shown. A reminder that arrives late is a nuisance; one silently eaten
    by a sleeping app is the failure this whole subsystem exists to prevent.

    So the client acknowledges (`{"type": "seen", "id": n}`) and `mark_seen`
    below is the only thing that marks a row fired. Un-acknowledged reminders
    come round again on the next sweep, which is exactly right: they have not
    been delivered.
    """
    items = await run_in_threadpool(reminders.due)
    if not items:
        return 0
    sent = 0
    for item in items:
        frame = _frame(item)
        live = await listeners.send(frame)
        if live:
            sent += 1
            continue

        # Nobody has it open. Web Push is the only thing that can reach a
        # closed PWA — it has no process, no alarms and no way to wake itself,
        # so without this a reminder can only arrive while you are already
        # looking, which is exactly when you least need telling.
        pushed = await run_in_threadpool(push.send, {
            "title": "Jarvis",
            "body": frame["text"],
            "tag": f"reminder-{item['id']}",
            "id": item["id"],
        })
        if pushed:
            # A push that the service ACCEPTED is not one a person has seen —
            # same rule as the socket. The client acknowledges from its own
            # notification handler, and until then the row stays pending.
            log.info("pushed to %d subscriber(s): %s", pushed, item["message"][:50])
            sent += 1
    if not sent and items:
        log.info("%d reminder(s) waiting for somewhere to go", len(items))
    return sent


async def mark_seen(reminder_id: int) -> None:
    """A client has actually shown one. Only now is it delivered."""
    if not reminder_id:
        return
    await run_in_threadpool(reminders.delivered, int(reminder_id))
    log.info("reminder acknowledged: %s", reminder_id)


async def loop(stop: asyncio.Event) -> None:
    """Watch the diary for as long as the server is up."""
    while not stop.is_set():
        try:
            await deliver_due()
        except Exception:  # noqa: BLE001  (a bad row must not end the loop)
            log.exception("reminder sweep failed")
        try:
            await catch_up()
        except Exception:  # noqa: BLE001
            log.exception("embedding sweep failed")
        # Waiting on the event rather than sleeping means shutdown is immediate
        # instead of taking up to a full interval.
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=INTERVAL)
