"""Reminders — scheduled in the database, announced wherever Jarvis is running.

Rewritten in phase 05. The old version kept a list in memory and a thread to
watch it, which worked on the desktop and failed silently in the cloud: nobody
ever called `start()` there, so the loop never ran, and a reminder lived exactly
as long as the HTTP request that created it. Asking for one appeared to work.
Nothing ever arrived. That is a worse failure than an error message.

So the diary is `core.memory.agenda` — SQLite, and therefore the same diary on
the phone, in the browser and on the PC. This module is only about *delivery*:

* On the desktop, `start(speak)` runs a thread that says them out loud.
* In the cloud, `sweep()` is called on a schedule and hands back whatever is due
  so the server can push it. See server/app.py.

Both go through `agenda.ready()` and both call `mark_fired`, so a reminder is
delivered once even with a desktop and a server watching the same database.
"""
from __future__ import annotations

import re
import threading

from core import clock, config
from core.memory import agenda

# Every thirty seconds. These are things like "leave in twenty minutes", not
# stopwatch ticks, and the per-second poll the old version used would be a
# needless query against a remote database, forever.
INTERVAL = 30.0

_speak = None
_started = False
_stop = threading.Event()


def add(delay_seconds: float, message: str) -> str:
    """Schedule a reminder that many seconds from now.

    The old signature, kept because `actions.set_reminder` and the rule-based
    brain both still call it. It writes to the database now like everything else.
    """
    when = clock.now() + max(0.0, float(delay_seconds))
    agenda.add(when, message)
    return f"Reminder set for {clock.say(when)}."


def schedule(when_text: str, message: str, warn: str = "") -> str:
    """Put something in the diary from what Rohan actually said.

    `when_text` is any phrase — "in 20 minutes", "18 sept", "tomorrow at 5".
    `warn` is how far ahead to say something about it, if that should be earlier
    than the thing itself: "the day before", "an hour before".

    Returns the sentence to say back, which always contains the time as Jarvis
    understood it. Reading it back is the whole safety net: it is how a
    misheard Thursday gets caught now rather than the morning after the exam.
    """
    rule, days = clock.parse_repeat(when_text)
    due, all_day = clock.parse_when(when_text)
    if due is None:
        return "I need a time for that — say when, and I'll put it down."
    if due < clock.now() - 60:
        return f"That's already passed ({clock.say(due, all_day)}). Say when again?"

    lead = clock.parse_gap(warn) if warn else None
    remind_at = due - lead if lead else due
    if remind_at < clock.now():
        # Warning about it "the day before" when it is this afternoon just means
        # now. Better than never mentioning it, which is what the alternative —
        # a lead time already in the past — would silently do.
        remind_at = clock.now()

    kind = "event" if (all_day or lead) else "reminder"
    new_id = agenda.add(due, message, remind_at=remind_at, all_day=all_day, kind=kind,
                        repeat_rule=rule, repeat_days=days)
    if new_id is None:
        return "I couldn't write that down just now."

    if rule:
        # A repeating thing is said back as the pattern, not as its first
        # occurrence: "every Monday and Wednesday" is what was agreed, and
        # hearing only "on Monday" back is how you fail to notice that the
        # Wednesday never registered.
        said = (f"Noted: {message}, {clock.repeat_words(rule, days)}"
                f"{'' if all_day else ' at ' + clock._clock_words(clock.local(due))}. "
                f"First one {clock.say(due, all_day)}.")
        return said

    said = f"Noted: {message} {clock.say(due, all_day)}."
    if lead and abs(remind_at - due) > 60:
        said += f" I'll remind you {clock.say(remind_at)}."

    # And, for anything there is work to be done about, one unprompted "how is
    # it going?" partway there. Said out loud when it is set, because an
    # assistant that is going to ask you something later should tell you so
    # rather than surprising you with it.
    asked = plan_checkin(new_id, due, message)
    if asked:
        said += f" I'll check in with you {clock.say(asked)}."
    return said


# ---------------------------------------------------------------------------
# Asking how it is going
# ---------------------------------------------------------------------------
#
# The difference between a diary and an assistant. A diary holds "exam on the
# 18th" and says it back on the 18th. Someone who is actually helping asks, a
# few days beforehand, how the preparation is going — unprompted, because they
# remembered on their own.
#
# Two rules keep it from becoming nagging, which is the only way this feature
# fails. It asks ONCE per thing, and only about things there is something to be
# done about: an exam, a deadline, a submission. Nobody wants to be asked how
# their dentist appointment is coming along.

# Things you prepare for. A check-in only makes sense where there is work
# between now and then.
_WORTH_ASKING = re.compile(
    r"\b(exam|test|quiz|ct\b|midterm|final|viva|assignment|homework|"
    r"submission|submit|deadline|due|project|paper|report|thesis|"
    r"presentation|present|interview|defence|defense|application|apply|"
    r"proposal|draft|revision|revise|prepare|study)\b", re.I)

# Below this there is no room to ask and still be useful — the reminder itself
# is doing that job.
MIN_GAP_FOR_CHECKIN = 3 * 86400.0
# How far through the wait to ask. Early enough that the answer can change what
# happens, late enough that there is something to report.
CHECKIN_POINT = 0.55


def worth_asking_about(message: str) -> bool:
    return bool(_WORTH_ASKING.search(message or ""))


def checkin_question(message: str) -> str:
    """The wording. A question, not an announcement.

    "Exam on Friday" is a reminder. "How is the exam going?" is a person. The
    whole point of this feature lives in that difference, so the phrasing is not
    left to a model that might be having an off day — or unavailable entirely.
    """
    subject = " ".join((message or "").split())
    return f"How's it going with {subject}?"


def plan_checkin(parent_id: int, due: float, message: str,
                 base: float | None = None) -> float | None:
    """Schedule one "how is it going?" between now and `due`, if it is warranted.

    Returns when it will ask, or None if it decided not to.
    """
    now = clock.now() if base is None else base
    gap = due - now
    if gap < MIN_GAP_FOR_CHECKIN or not worth_asking_about(message):
        return None

    when = now + gap * CHECKIN_POINT
    # Never in the small hours. A question at 4am is not a friend asking.
    local = clock.local(when)
    if local.hour < 8:
        when = clock.epoch(local.replace(hour=9, minute=0, second=0, microsecond=0))
    elif local.hour > 21:
        when = clock.epoch(local.replace(hour=20, minute=0, second=0, microsecond=0))
    if not (now < when < due):
        return None

    stored = agenda.add(when, checkin_question(message), remind_at=when,
                        all_day=False, kind="checkin", parent=parent_id)
    return when if stored else None


def upcoming_text(limit: int = 8) -> str:
    """The diary as a sentence or two, for reading aloud."""
    items = agenda.upcoming(limit)
    if not items:
        return "Nothing in the diary."
    if len(items) == 1:
        return agenda.describe(items[0]) + "."
    return "; ".join(agenda.describe(item) for item in items) + "."


def cancel(fragment: str) -> int:
    """Drop upcoming items matching a word or phrase. Returns how many went."""
    return agenda.cancel(fragment)


def pending() -> int:
    return agenda.count()


def wording(item: dict) -> str:
    """What a due reminder sounds like when it arrives.

    An event warned about ahead of time reads differently from a reminder going
    off at its own moment — "tomorrow: exam" rather than "reminder: exam" — and
    getting that wrong makes Jarvis sound like it has lost track of the date.
    """
    if item.get("kind") == "checkin":
        # Already phrased as a question when it was planned; announcing it as
        # "Reminder:" would turn a friendly nudge back into an alarm.
        return item["message"]

    title = f", {config.USER_TITLE}" if config.USER_TITLE else ""
    early = item["due"] - item.get("remind_at", item["due"]) > 60
    if early:
        return f"{clock.say(item['due'], bool(item.get('all_day'))).capitalize()}: {item['message']}."
    return f"Reminder{title}: {item['message']}"


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def due() -> list[dict]:
    """Everything whose moment has arrived and which has not been announced."""
    return agenda.ready()


def delivered(reminder_id: int) -> None:
    """Say that one has been announced, so it is not announced again."""
    agenda.mark_fired(reminder_id)


def sweep() -> list[dict]:
    """Take everything that is due, mark it delivered, and hand it back.

    The desktop's version: it speaks immediately and out loud, so delivery is
    certain by the time this returns. The cloud must not use it — there,
    delivery depends on somebody having the app open, and marking an item fired
    with nobody listening is how a reminder disappears for good. See
    server/nudges.py, which calls `due` and `delivered` separately.
    """
    items = due()
    for item in items:
        delivered(item["id"])
    return items


def start(speak_callback) -> None:
    """Begin announcing reminders out loud. Desktop only — see the module note."""
    global _speak, _started
    _speak = speak_callback
    if not _started:
        _started = True
        _stop.clear()
        threading.Thread(target=_loop, daemon=True).start()


def stop() -> None:
    _stop.set()


def _loop() -> None:
    while not _stop.is_set():
        try:
            for item in sweep():
                if _speak:
                    _speak(wording(item))
        except Exception:  # noqa: BLE001  (a bad row must not kill the thread)
            pass
        # Waiting on the event rather than sleeping means shutting down is
        # immediate instead of taking up to a full interval.
        _stop.wait(INTERVAL)
