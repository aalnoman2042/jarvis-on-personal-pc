"""Time, as Rohan experiences it — and the words he says it in.

Two problems, both of which make a reminder useless rather than merely wrong.

**The server is not where he is.** The cloud core runs in UTC on a machine in
Singapore. "18 September" means the 18th where Rohan is standing, and a reminder
that fires six hours off is a reminder that failed. So every date here is built
in *his* timezone and only then flattened to an epoch, which is the one form
that means the same thing everywhere and is what the database stores.

**He does not speak ISO 8601.** He says "tomorrow at five", "18 sept", "in 20
minutes", "the day before". Making a model emit exact timestamps instead is
tempting and unreliable — it invents the year, forgets the timezone, and the
offline brain cannot do it at all. Parsing the phrase here means every brain,
including the rule-based one, gets dates for free and gets the same ones.

Nothing here touches the network, the disk, or a model. It is arithmetic on
strings: fast, testable, and working with the PC switched off.
"""
from __future__ import annotations

import datetime as dt
import os
import re

# Rohan is in Bangladesh, which has no daylight saving — a fixed offset is
# genuinely correct there. The zone name is still preferred when the platform
# has a tz database, so moving him somewhere with DST is one environment
# variable rather than a rewrite. Windows ships no system tzdata, which is why
# this falls back instead of depending on the `tzdata` package.
TZ_NAME = os.getenv("VONDO_TZ", "Asia/Dhaka")
TZ_OFFSET_HOURS = float(os.getenv("VONDO_UTC_OFFSET", "6"))


def _zone() -> dt.tzinfo:
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(TZ_NAME)
    except Exception:  # noqa: BLE001  (no tzdata on this platform, or a bad name)
        return dt.timezone(dt.timedelta(hours=TZ_OFFSET_HOURS))


ZONE = _zone()

MINUTE = 60.0
HOUR = 3600.0
DAY = 86400.0

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1, "wednesday": 2,
    "wed": 2, "thursday": 3, "thurs": 3, "thur": 3, "thu": 3, "friday": 4,
    "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}
# Vague times of day, resolved to an hour. Chosen to be defensible rather than
# clever: a reminder at the wrong end of "evening" is worse than a boring 7pm.
VAGUE = {
    "midnight": 0, "dawn": 6, "morning": 9, "noon": 12, "midday": 12,
    "afternoon": 15, "evening": 19, "tonight": 21, "night": 21,
}
UNITS = {
    "min": MINUTE, "mins": MINUTE, "minute": MINUTE, "minutes": MINUTE,
    "hr": HOUR, "hrs": HOUR, "hour": HOUR, "hours": HOUR,
    "day": DAY, "days": DAY, "night": DAY, "nights": DAY,
    "week": DAY * 7, "weeks": DAY * 7,
    "month": DAY * 30, "months": DAY * 30, "year": DAY * 365, "years": DAY * 365,
}
# "the" counts as one because the phrase this exists for is "the day before" —
# which is how anyone actually asks to be warned about an exam.
WORD_NUMBERS = {
    "a": 1, "an": 1, "the": 1, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "sixty": 60,
}

# The hour a date with no time gets. Nine: early enough to be useful for the day
# ahead, late enough not to wake anyone.
DEFAULT_HOUR = 9

_UNIT_RE = "|".join(sorted(UNITS, key=len, reverse=True))
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))


# ---------------------------------------------------------------------------
# Now
# ---------------------------------------------------------------------------

def now() -> float:
    """Seconds since the epoch. One place, so tests can reason about it."""
    return dt.datetime.now(dt.timezone.utc).timestamp()


def local(ts: float | None = None) -> dt.datetime:
    """An epoch as the wall clock where Rohan is."""
    return dt.datetime.fromtimestamp(now() if ts is None else ts, ZONE)


def epoch(when: dt.datetime) -> float:
    """A local wall-clock time back to an epoch, assuming his zone if naive."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=ZONE)
    return when.timestamp()


def today_line() -> str:
    """What day it is, for the system prompt.

    Without this a model dates everything from its training cut-off, so "next
    Thursday" lands in the wrong year and nobody finds out until it doesn't fire.
    """
    return local().strftime("%A, %d %B %Y, %H:%M")


# ---------------------------------------------------------------------------
# Reading a phrase
# ---------------------------------------------------------------------------

def _number(word: str) -> float | None:
    word = word.strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", word):
        return float(word)
    return float(WORD_NUMBERS[word]) if word in WORD_NUMBERS else None


def parse_gap(text: str) -> float | None:
    """A length of time — "20 minutes", "2 hrs", "a day" — in seconds.

    Used both for "in 20 minutes" and for how far ahead of something to warn.
    Returns None when the phrase is not a duration at all.
    """
    if not text:
        return None
    words = " ".join(text.strip().lower().split())
    if words in ("now", "immediately", "right now", "at once"):
        return 0.0
    half = re.search(r"half\s+(?:an?\s+)?(hour|hr|day)", words)
    if half:
        return UNITS[half.group(1)] / 2
    match = re.search(r"(\d+(?:\.\d+)?|[a-z]+)\s*(" + _UNIT_RE + r")\b", words)
    if not match:
        return None
    count = _number(match.group(1))
    return None if count is None else count * UNITS[match.group(2)]


def _time_of_day(text: str) -> tuple[int, int] | None:
    """An hour and minute out of a phrase, or None if it names no time."""
    words = text.lower()

    match = re.search(r"\b(\d{1,2})[:.](\d{2})\s*(am|pm)?", words)
    if match:
        hour, minute, suffix = int(match.group(1)), int(match.group(2)), match.group(3)
        if suffix == "pm" and hour < 12:
            hour += 12
        elif suffix == "am" and hour == 12:
            hour = 0
        return (hour % 24, minute % 60)

    match = re.search(r"\b(\d{1,2})\s*(am|pm)\b", words)
    if match:
        hour = int(match.group(1))
        if match.group(2) == "pm" and hour < 12:
            hour += 12
        elif match.group(2) == "am" and hour == 12:
            hour = 0
        return (hour % 24, 0)

    # A bare number only counts after "at" — otherwise the 18 in "18 sept"
    # becomes six in the evening. Taken literally rather than guessed at: being
    # twelve hours out is the worst way for this to be wrong.
    match = re.search(r"\bat\s+(\d{1,2})\b(?!\s*(?:st|nd|rd|th|/|-|:))", words)
    if match:
        return (int(match.group(1)) % 24, 0)

    for word, hour in VAGUE.items():
        if re.search(r"\b" + word + r"\b", words):
            return (hour, 0)
    return None


def _with_year(day: int, month: int, base: dt.datetime) -> dt.date | None:
    """A day and month with no year means the next one coming.

    Said in December, "18 January" is next year. Rolling forward is right far
    more often than assuming this year and quietly scheduling something into the
    past, where it either fires at once or never.
    """
    for year in (base.year, base.year + 1):
        try:
            candidate = dt.date(year, month, day)
        except ValueError:
            return None
        if candidate >= base.date():
            return candidate
    return None


def _date_part(text: str, base: dt.datetime) -> dt.date | None:
    """The day a phrase names, or None if it only names a time."""
    words = text.lower()

    if re.search(r"\bday after tomorrow\b", words):
        return (base + dt.timedelta(days=2)).date()
    if re.search(r"\btomorrow\b", words):
        return (base + dt.timedelta(days=1)).date()
    if re.search(r"\b(today|tonight|this (?:evening|afternoon|morning))\b", words):
        return base.date()

    match = re.search(r"\bnext\s+(week|month|year)\b", words)
    if match:
        ahead = {"week": 7, "month": 30, "year": 365}[match.group(1)]
        return (base + dt.timedelta(days=ahead)).date()

    iso = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", words)
    if iso:
        try:
            return dt.date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None

    match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + _MONTH_RE + r")\b", words)
    if match:
        return _with_year(int(match.group(1)), MONTHS[match.group(2)], base)

    match = re.search(r"\b(" + _MONTH_RE + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b", words)
    if match:
        return _with_year(int(match.group(2)), MONTHS[match.group(1)], base)

    # "18/9" or "18-9-2026" — day first, which is how Rohan writes dates.
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", words)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        if match.group(3):
            year = int(match.group(3))
            year += 2000 if year < 100 else 0
            try:
                return dt.date(year, month, day)
            except ValueError:
                return None
        return _with_year(day, month, base)

    for name in sorted(WEEKDAYS, key=len, reverse=True):
        if re.search(r"\b" + name + r"\b", words):
            ahead = (WEEKDAYS[name] - base.weekday()) % 7
            if ahead == 0 or re.search(r"\bnext\b", words):
                ahead = ahead or 7
            return (base + dt.timedelta(days=ahead)).date()
    return None


def parse_when(text: str, base: float | None = None) -> tuple[float | None, bool]:
    """Turn a spoken phrase into (epoch, all_day).

    `all_day` says the phrase named a day but no time — "18 September". That
    difference has to survive: it decides whether Jarvis says "on the 18th" or
    "at nine on the 18th", and a time nobody gave, read back confidently, is how
    you stop trusting the thing.

    Returns (None, False) when the phrase names no time at all, so the caller can
    ask instead of inventing one.
    """
    if not text or not text.strip():
        return (None, False)
    words = " ".join(text.lower().split())
    stamp = now() if base is None else base
    start = local(stamp)

    # "in 20 minutes" is a gap from now, not a date, and is checked first: "in 2
    # days" matches the day parser too, and only one of the two readings keeps
    # the time of day.
    relative = re.match(r"^(?:in|after)\s+(.+)$", words)
    if relative:
        rest = relative.group(1)
        gap = parse_gap(rest)
        if gap is not None:
            if gap < DAY:
                return (stamp + gap, False)
            # "in 3 days" keeps the current time of day, which is what people
            # mean, unless they named an hour as well.
            moment = start + dt.timedelta(seconds=gap)
            clock = _time_of_day(words)
            if clock:
                moment = moment.replace(hour=clock[0], minute=clock[1])
            return (epoch(moment.replace(second=0, microsecond=0)), False)

    # A bare duration: "20 minutes", "2h". Only when the whole phrase is one,
    # so "the 20 minutes before class" is not mistaken for a delay.
    if re.fullmatch(r"\d+(?:\.\d+)?\s*(?:" + _UNIT_RE + r")", words):
        gap = parse_gap(words)
        if gap is not None:
            return (stamp + gap, False)

    day = _date_part(words, start)
    clock = _time_of_day(words)

    if day is None and clock is None:
        return (None, False)

    if day is None:
        # A time with no day: today if it is still ahead, otherwise tomorrow.
        moment = start.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
        if moment <= start:
            moment += dt.timedelta(days=1)
        return (epoch(moment), False)

    all_day = clock is None
    hour, minute = clock if clock else (DEFAULT_HOUR, 0)
    moment = dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZONE)
    return (epoch(moment), all_day)


# ---------------------------------------------------------------------------
# Saying it back
# ---------------------------------------------------------------------------

def _clock_words(moment: dt.datetime) -> str:
    """"5pm", "9:30am" — built by hand because %-I is not portable to Windows."""
    hour = moment.hour % 12 or 12
    part = "am" if moment.hour < 12 else "pm"
    return f"{hour}:{moment.minute:02d}{part}" if moment.minute else f"{hour}{part}"


def _date_words(moment: dt.datetime) -> str:
    day = moment.day
    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    year = "" if moment.year == local().year else f" {moment.year}"
    return f"{day}{suffix} {moment.strftime('%B')}{year}"


def say(ts: float, all_day: bool = False, base: float | None = None) -> str:
    """How Jarvis reads a time aloud — "tomorrow at 5pm", "on 18th September".

    Said back every time something is scheduled. It is the only way Rohan finds
    out that "next thursday" was heard as the wrong Thursday, and he finds out
    now rather than the morning after the exam.
    """
    moment = local(ts)
    start = local(base)
    days = (moment.date() - start.date()).days
    at = "" if all_day else " at " + _clock_words(moment)

    if days == 0:
        return "today" if all_day else "later today" + at
    if days == 1:
        return "tomorrow" + at
    if 2 <= days <= 6:
        return "on " + moment.strftime("%A") + at
    return "on " + _date_words(moment) + at


# ---------------------------------------------------------------------------
# Things that happen again
# ---------------------------------------------------------------------------

REPEATS = ("daily", "weekdays", "weekly", "monthly", "yearly")


def parse_repeat(text: str) -> tuple[str, list[int]]:
    """Read a recurrence out of a phrase: ("weekly", [0, 2]) for "every Mon and Wed".

    Returns ("", []) when the phrase names no repetition, which is most of them.

    Weekly with named days is the case that matters and the one a simpler
    implementation gets wrong: a university timetable is "Monday and Wednesday",
    not "every 7 days from today", and storing it as the latter means moving one
    week's class moves every week after it.
    """
    if not text:
        return ("", [])
    words = " ".join(text.lower().split())

    if not re.search(r"\b(every|each|daily|weekly|monthly|yearly|weekdays|weekday)\b", words):
        return ("", [])

    # Named days win over everything: "every monday and wednesday".
    days = sorted({
        WEEKDAYS[name]
        for name in WEEKDAYS
        if re.search(r"\b" + name + r"\b", words)
    })
    if days:
        return ("weekly", days)

    if re.search(r"\b(weekdays?|working days?|every work day)\b", words):
        return ("weekdays", [])
    if re.search(r"\b(daily|every day|each day|every single day)\b", words):
        return ("daily", [])
    if re.search(r"\b(weekly|every week|each week)\b", words):
        return ("weekly", [])
    if re.search(r"\b(monthly|every month|each month)\b", words):
        return ("monthly", [])
    if re.search(r"\b(yearly|annually|every year|each year)\b", words):
        return ("yearly", [])
    return ("", [])


def next_occurrence(after: float, rule: str, days: list[int] | None = None) -> float | None:
    """The next time a repeating thing happens, strictly after `after`.

    Advances in *local* time rather than by adding seconds. Adding 86400 to an
    epoch is only the same as "tomorrow" while the offset holds; the day and the
    time of day are what a person means, so those are what move.
    """
    if rule not in REPEATS:
        return None
    moment = local(after)

    if rule == "daily":
        return epoch(moment + dt.timedelta(days=1))

    if rule == "weekdays":
        step = moment
        for _ in range(7):
            step += dt.timedelta(days=1)
            if step.weekday() < 5:
                return epoch(step)
        return None

    if rule == "weekly":
        wanted = sorted(days or [moment.weekday()])
        step = moment
        for _ in range(14):
            step += dt.timedelta(days=1)
            if step.weekday() in wanted:
                return epoch(step)
        return None

    if rule == "monthly":
        year, month = moment.year, moment.month + 1
        if month > 12:
            year, month = year + 1, 1
        # The 31st does not exist in every month. Falling back to the last day
        # is what a person means by "the 31st of next month" when there is no
        # 31st — skipping the month entirely would silently drop an occurrence.
        day = min(moment.day, _days_in(year, month))
        return epoch(moment.replace(year=year, month=month, day=day))

    if rule == "yearly":
        try:
            return epoch(moment.replace(year=moment.year + 1))
        except ValueError:  # 29 February
            return epoch(moment.replace(year=moment.year + 1, day=28))
    return None


def _days_in(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (dt.date(year, month + 1, 1) - dt.timedelta(days=1)).day


def repeat_words(rule: str, days: list[int] | None = None) -> str:
    """How a recurrence reads aloud: "every Monday and Wednesday"."""
    if rule == "daily":
        return "every day"
    if rule == "weekdays":
        return "every weekday"
    if rule == "monthly":
        return "every month"
    if rule == "yearly":
        return "every year"
    if rule == "weekly":
        if not days:
            return "every week"
        names = [n for n in ("Monday", "Tuesday", "Wednesday", "Thursday",
                             "Friday", "Saturday", "Sunday")]
        chosen = [names[d] for d in sorted(days)]
        if len(chosen) == 1:
            return f"every {chosen[0]}"
        return "every " + ", ".join(chosen[:-1]) + " and " + chosen[-1]
    return ""


def was(ts: float, base: float | None = None) -> str:
    """When something happened, in the past tense — "yesterday", "on 12 August".

    `say` is written for things that have not happened yet, so it reaches for
    "later today" and "tomorrow". Handed a timestamp from the archive it
    produces "later today at 3pm" for a sentence spoken this morning, which
    reads as though Jarvis has lost track of which way time runs.
    """
    moment = local(ts)
    start = local(base)
    days = (start.date() - moment.date()).days
    at = " at " + _clock_words(moment)

    if days <= 0:
        return "earlier today" + at
    if days == 1:
        return "yesterday" + at
    if days < 7:
        return f"{days} days ago"
    if days < 14:
        return "last week"
    if days < 60:
        return f"{days // 7} weeks ago"
    return "on " + _date_words(moment)


def until(ts: float, base: float | None = None) -> str:
    """How far away something is, in words: "in 3 days", "in 20 minutes"."""
    gap = ts - (now() if base is None else base)
    if gap < 0:
        return "overdue"
    if gap < MINUTE:
        return "in under a minute"
    if gap < HOUR:
        count = int(gap // MINUTE)
        return f"in {count} minute{'s' if count != 1 else ''}"
    if gap < DAY:
        count = int(gap // HOUR)
        return f"in {count} hour{'s' if count != 1 else ''}"
    count = int(gap // DAY)
    return f"in {count} day{'s' if count != 1 else ''}"
