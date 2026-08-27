"""The morning briefing — what today looks like, before you ask.

The one proactive thing Jarvis does. Everything else waits to be spoken to;
this is the assistant volunteering something, which is the difference between a
chatbot and an assistant.

**It is composed, not generated.** No model is called. The facts come out of the
diary and the database, and the sentences are written here. Three reasons, all
of which matter more than the prose being livelier:

* it must work when Groq's free tier is exhausted and Gemini is down, which is
  exactly when you would least like to be told nothing;
* it costs no quota, every morning, forever;
* a model asked to summarise a diary will eventually invent an appointment, and
  a briefing you have to double-check is not a briefing.

**It says nothing rather than padding.** A quiet day gets a short line, not a
paragraph of filler about how quiet it is. The whole thing is worth reading only
while it stays worth reading.
"""
from __future__ import annotations

from core import clock, config
from core.memory import agenda
from core.memory import tasks

# How far ahead "today" reaches. Something at 1am tomorrow is tonight's problem,
# not tomorrow morning's.
DAY_AHEAD = 18 * 3600.0
SOON_AHEAD = 3 * 24 * 3600.0


def _greeting(hour: int) -> str:
    if hour < 5:
        return "You're up late"
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


def _join(items: list[str]) -> str:
    """Read a list the way a person would: a, b and c."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def compose(pc_online: bool = False, spoken: bool = False) -> str:
    """Today, in a few sentences. Empty string if there is genuinely nothing.

    `spoken` drops the parts that only make sense on a screen, so the same
    briefing can be read aloud without sounding like a form being filled in.
    """
    now = clock.now()
    here = clock.local(now)
    lines: list[str] = []

    title = f", {config.USER_TITLE}" if config.USER_TITLE else ""
    lines.append(f"{_greeting(here.hour)}{title}.")

    upcoming = agenda.upcoming(20)
    today = [i for i in upcoming if i["due"] <= now + DAY_AHEAD]
    soon = [i for i in upcoming if now + DAY_AHEAD < i["due"] <= now + SOON_AHEAD]

    if today:
        parts = [f"{i['message']} {clock.say(i['due'], bool(i.get('all_day')), now)}"
                 for i in today[:4]]
        lines.append(f"Today: {_join(parts)}.")
        if len(today) > 4:
            lines.append(f"{len(today) - 4} more after that.")
    else:
        lines.append("Nothing in the diary for today.")

    if soon:
        # Named but not detailed. The point of mentioning the exam three days
        # out is that you remember it exists, not that you plan around it now.
        nearest = soon[0]
        lines.append(
            f"Coming up: {nearest['message']} "
            f"{clock.say(nearest['due'], bool(nearest.get('all_day')), now)}"
            + (f", and {len(soon) - 1} other thing{'s' if len(soon) > 2 else ''}."
               if len(soon) > 1 else ".")
        )

    # What is on the list, because "today" is not only appointments. Overdue
    # first: a deadline that has passed is the one thing that stops being
    # fixable, and a briefing that omits it is being polite at your expense.
    todo = tasks.open_tasks(12)
    if todo:
        late = [t for t in todo if t.get("due") and t["due"] < now]
        big = [t for t in todo if t.get("priority") == tasks.HIGH and t not in late]
        if late:
            lines.append(f"Overdue: {_join([t['text'] for t in late[:3]])}.")
        if big:
            lines.append(f"Top of the list: {_join([t['text'] for t in big[:2]])}.")
        rest = len(todo) - len(late[:3]) - len(big[:2])
        if rest > 0:
            lines.append(f"{rest} other thing{'s' if rest != 1 else ''} to do.")

    # Overdue is worth saying out loud, because the whole point of a diary is
    # that nothing silently rots in it.
    stale = [i for i in agenda.ready(now) if now - i["due"] > 3600]
    if stale:
        lines.append(
            f"Still outstanding: {_join([i['message'] for i in stale[:3]])}."
        )

    # The thing that makes this an assistant rather than a list: asking about
    # something you said you would do, unprompted, because it remembered on its
    # own. Phrased as a question and marked asked, so it happens exactly once —
    # chasing the same commitment every morning is how a helpful assistant
    # becomes a thing you close.
    for job in tasks.noticed_to_chase():
        lines.append(f"You mentioned you'd {job['text']} — did that happen?")
        tasks.mark_asked(job["id"])

    if not spoken and not pc_online:
        lines.append("Your PC is asleep — I'll use your phone for anything that needs opening.")

    return " ".join(lines)


def is_new_day(last_seen: float | None) -> bool:
    """True if the last briefing was on an earlier day than now.

    Compared by calendar day in Rohan's timezone, not by elapsed hours — a
    briefing at 11pm and another at 1am are two days and should be, while one at
    7am and another at 9pm the same day is one.
    """
    if not last_seen:
        return True
    return clock.local(last_seen).date() < clock.local().date()
