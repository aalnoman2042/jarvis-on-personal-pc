"""The week, looked back on.

The morning briefing answers "what is today". This answers "what has actually
been happening", which is the question you cannot answer for yourself — nobody
can remember a week accurately, and everyone is sure they can.

**Counted, not guessed.** Every figure here comes from rows that already exist:
tasks finished, things added, what was in the diary, what was talked about. The
one place a model is involved is the closing observation, and even that has a
composed fallback — a report that only appears when a free tier is up is a
report you cannot rely on, and this is the one that runs unattended.

**Patterns come from arithmetic.** "You talk about NILM more than anything else"
is a word count over Rohan's own messages, not an inference. It costs nothing,
it can be checked, and it cannot hallucinate a topic he never mentioned. That is
the whole of the "learn from my data" idea that is worth having: the expensive
part of an assistant should be the reasoning, never the remembering.

Once a week, so it stays worth reading. A daily version of this is a chore.
"""
from __future__ import annotations

import re
from collections import Counter

from core import clock, config
from core.memory import agenda, recall, store, tasks

WEEK = 7 * 86400.0

# Words that say nothing about a week. The recall stopword list plus the ones
# that are noise specifically in a "what did you talk about" count.
_NOISE = recall.STOPWORDS | {
    "jarvis", "please", "thanks", "thank", "okay", "yes", "yeah", "hey", "hello",
    "open", "close", "set", "add", "make", "tell", "show", "give", "need",
    "want", "going", "think", "good", "time", "today", "tomorrow", "week",
    "day", "days", "something", "anything", "nothing", "really", "still",
}


def _topics(since: float, limit: int = 4) -> list[tuple[str, int]]:
    """What Rohan actually talked about, by counting his own words.

    His messages only, never Jarvis's replies: counting both would rank the
    assistant's own vocabulary, and "reminder" would come top of every week.
    """
    conn = store.connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT user FROM messages WHERE ts >= ?", (since,)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    counts: Counter[str] = Counter()
    for row in rows:
        seen = set()
        for word in re.findall(r"[a-z0-9]{4,}", (row["user"] or "").lower()):
            # Once per message: saying "NILM" six times in one sentence is one
            # mention of NILM, not six.
            if word in _NOISE or word in seen:
                continue
            seen.add(word)
            counts[word] += 1
    return [(w, n) for w, n in counts.most_common(limit) if n >= 2]


def _busiest_hours(since: float) -> str:
    """When in the day he is actually talking to it.

    Real observed behaviour rather than a self-report, which is the only kind
    of habit figure worth showing — nobody keeps a manual log for more than a
    fortnight, and a stale one is worse than none.
    """
    conn = store.connect()
    if conn is None:
        return ""
    try:
        rows = conn.execute(
            "SELECT ts FROM messages WHERE ts >= ?", (since,)).fetchall()
    except Exception:  # noqa: BLE001
        return ""
    if len(rows) < 8:
        return ""      # too little to claim a pattern from
    hours = Counter(clock.local(r["ts"]).hour for r in rows)
    top = hours.most_common(1)[0][0]
    if top < 5:
        return "late at night"
    if top < 12:
        return "in the morning"
    if top < 17:
        return "in the afternoon"
    if top < 21:
        return "in the evening"
    return "late in the evening"


def gather(since: float | None = None) -> dict:
    """The week's figures, all counted from rows that already exist."""
    start = (clock.now() - WEEK) if since is None else since
    done = tasks.done_since(start)
    open_now = tasks.open_tasks(50)
    conn = store.connect()

    said = 0
    added_tasks = 0
    if conn is not None:
        try:
            said = int(conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE ts >= ?",
                (start,)).fetchone()["n"] or 0)
            added_tasks = int(conn.execute(
                "SELECT COUNT(*) AS n FROM tasks WHERE created >= ?",
                (start,)).fetchone()["n"] or 0)
        except Exception:  # noqa: BLE001
            pass

    return {
        "from": start,
        "conversations": said,
        "finished": [t["text"] for t in done],
        "added": added_tasks,
        "still_open": len(open_now),
        "overdue": len([t for t in open_now if t.get("due") and t["due"] < clock.now()]),
        "coming": [agenda.describe(i) for i in agenda.upcoming(5)],
        "topics": _topics(start),
        "busiest": _busiest_hours(start),
    }


def _observation(data: dict) -> str:
    """The one line worth thinking about, composed from the figures.

    Deliberately arithmetic rather than a model. Everything it can say is
    something the numbers already show, which means it can be argued with — and
    a claim about someone's week that they cannot check is not worth making.
    """
    finished, added = len(data["finished"]), data["added"]
    if data["overdue"]:
        return (f"{data['overdue']} thing{'s' if data['overdue'] != 1 else ''} "
                f"on the list {'have' if data['overdue'] != 1 else 'has'} gone "
                f"past its date. Those first.")
    if added >= 3 and finished == 0:
        return (f"You added {added} things this week and finished none of them. "
                f"Worth picking one.")
    if added > finished * 2 and added >= 4:
        return (f"{added} added against {finished} finished — the list is "
                f"growing faster than it is shrinking.")
    if finished and finished >= added:
        return f"{finished} finished against {added} added. That is the right way round."
    if data["topics"]:
        return (f"Most of what you talked about was "
                f"{data['topics'][0][0]}.")
    return ""


def compose(since: float | None = None, data: dict | None = None) -> str:
    """The week, in a few sentences. Empty if there is nothing to report.

    `data` lets a caller that already has the figures pass them in. Gathering
    them is seven queries including two scans of the week's messages, and the
    endpoint wants both the prose and the numbers — doing it twice per request
    is the kind of waste that is invisible until the free tier notices.
    """
    data = gather(since) if data is None else data
    if not data["conversations"] and not data["finished"] and not data["added"]:
        return ""

    title = f", {config.USER_TITLE}" if config.USER_TITLE else ""
    lines = [f"Your week{title}."]

    if data["finished"]:
        names = data["finished"][:3]
        more = len(data["finished"]) - len(names)
        lines.append("Finished: " + ", ".join(names)
                     + (f", and {more} more." if more > 0 else "."))
    else:
        lines.append("Nothing was ticked off the list.")

    if data["still_open"]:
        lines.append(f"{data['still_open']} still to do"
                     + (f", {data['overdue']} of them overdue." if data["overdue"]
                        else "."))

    if data["topics"]:
        words = ", ".join(w for w, _ in data["topics"][:3])
        lines.append(f"Mostly you talked about {words}.")
    if data["busiest"]:
        lines.append(f"You use me mostly {data['busiest']}.")

    if data["coming"]:
        lines.append(f"Next up: {data['coming'][0]}.")

    note = _observation(data)
    if note:
        lines.append(note)
    return " ".join(lines)


def is_new_week(last: float | None) -> bool:
    """True if the last report was in an earlier week than now.

    Compared by ISO week in Rohan's timezone rather than by elapsed days, so
    the report lands on the same day each week instead of drifting an hour
    later every time.
    """
    if not last:
        return True
    then, now = clock.local(last), clock.local()
    return (then.isocalendar()[:2]) < (now.isocalendar()[:2])
