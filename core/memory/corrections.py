"""Learning from being wrong.

Everything else in this package records what Rohan *said*. This records what he
*meant* when Jarvis got it wrong — and it exists because of one specific
failure he reported: he asked it to change a reminder he had already set, and it
became confused and made a second one. Nothing in the system learned anything
from that. The next week it would do exactly the same.

**Not model training.** A few thousand turns fine-tuned produces a worse model
that sounds slightly more like you. This is retrieval: the correction is stored
as text and put back in front of the model when the same kind of request comes
round again. It costs nothing, it works with every free tier exhausted, and it
cannot hallucinate a lesson that was never taught.

**Two ways in, and the taught ones are trusted more.** `teach()` is Rohan saying
outright "when I say move it, I mean change the time" — unambiguous, and it
never expires. `noticed()` is Jarvis inferring a correction from a rephrase,
which is a guess and is marked as one. Both are visible and deletable in
Settings, because something that silently changes how the assistant behaves and
cannot be inspected is not something anybody should have to live with.

**A wrong correction is worse than no correction, and worse than a wrong
recall.** A bad recall is noise in the prompt; a bad correction is an
instruction. So detection is deliberately conservative and would rather miss
three than invent one — the same trade as the relevance floor next door, for a
higher stake.

Same contract as the rest of the package: nothing here raises into a
conversation.
"""
from __future__ import annotations

import re

from core import clock
from core.memory import store

MAX_TEXT = 400
# Kept in the prompt, so this is a character budget rather than a count — the
# same reasoning as facts, which this sits beside.
BLOCK_CHARS = 500
MAX_SHOWN = 3

TAUGHT, NOTICED = "taught", "noticed"

# The opening of a sentence that is putting something right. Anchored to the
# START on purpose: "no" in the middle of a sentence is usually part of the
# request ("remind me no later than five"), while "no, I meant..." is only ever
# a correction. Trailing space or punctuation is required for the short ones so
# "not" does not match "nothing" and "no" does not match "notepad".
_OPENERS = (
    "no,", "no.", "no —", "no -", "nope",
    "not that", "not what", "that's not", "thats not", "that is not",
    "i meant", "i mean ", "i said", "wrong", "that's wrong", "incorrect",
    "no i ", "no you ", "i didn't ", "i didnt ", "you misunderstood",
    "not the", "i asked for", "i wanted",
)


def _clean(text: str) -> str:
    return " ".join((text or "").split())[:MAX_TEXT]


def opens_like_a_correction(text: str) -> bool:
    """Does this sentence begin by putting something right?

    Only the opening is examined. A correction announces itself in its first
    few words; anything later in a sentence is far more likely to be part of
    the request, and treating it as a correction is how the table fills with
    rubbish that then goes into the prompt as an instruction.
    """
    low = " ".join((text or "").lower().split())
    return any(low.startswith(opener) for opener in _OPENERS)


def _content(text: str) -> set:
    from core.memory import recall
    return {w for w in re.findall(r"[a-z0-9]+", recall._fold(text or ""))
            if len(w) >= 3 and w not in recall.STOPWORDS}


def looks_like_a_rephrase(previous: str, now: str) -> bool:
    """Is this the same request, said differently, immediately after?

    The signal is *overlap without repetition*: enough shared subject that it
    is plainly the same topic, but not the identical sentence — somebody who
    types the same thing twice is usually reacting to silence rather than to a
    wrong answer.
    """
    before, after = _content(previous), _content(now)
    if len(before) < 2 or len(after) < 2:
        return False
    if before == after:
        return False                      # said again, not said differently
    shared = before & after
    return len(shared) >= 2 and len(shared) / max(1, min(len(before), len(after))) >= 0.5


# ---------------------------------------------------------------------------
# Keeping them
# ---------------------------------------------------------------------------

def _add(asked: str, did: str, meant: str, source: str) -> int | None:
    conn = store.connect()
    asked, meant = _clean(asked), _clean(meant)
    if conn is None or not meant:
        return None
    try:
        # The same lesson twice is one lesson that has now happened twice, and
        # the count is what lets the prompt show the ones that keep biting.
        existing = conn.execute(
            "SELECT id, hits FROM corrections WHERE lower(meant) = ? LIMIT 1",
            (meant.lower(),)).fetchone()
        if existing:
            conn.execute(
                "UPDATE corrections SET hits = hits + 1, ts = ? WHERE id = ?",
                (round(clock.now(), 1), existing["id"]))
            conn.commit()
            return int(existing["id"])
        cursor = conn.execute(
            "INSERT INTO corrections(asked, did, meant, source, ts, hits) "
            "VALUES (?,?,?,?,?,1)",
            (asked, _clean(did), meant, source, round(clock.now(), 1)))
        conn.commit()
        return cursor.lastrowid
    except Exception:  # noqa: BLE001
        return None


def teach(when_i_say: str, i_mean: str) -> str:
    """Rohan saying outright what he means. Returns what to say back."""
    when_i_say, i_mean = _clean(when_i_say), _clean(i_mean)
    if not i_mean:
        return "Tell me what you'd like me to do instead."
    if _add(when_i_say, "", i_mean, TAUGHT) is None:
        return "I couldn't write that down just now."
    if when_i_say:
        return f"Understood — when you say “{when_i_say}” I'll {i_mean.rstrip('.')}."
    return f"Understood — I'll {i_mean.rstrip('.')}."


def noticed(asked: str, did: str, meant: str) -> int | None:
    """Jarvis inferring a correction. A guess, and marked as one."""
    return _add(asked, did, meant, NOTICED)


def all_corrections(limit: int = 50) -> list[dict]:
    conn = store.connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT * FROM corrections ORDER BY hits DESC, ts DESC LIMIT ?",
            (limit,)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [dict(r) for r in rows]


def forget(correction_id: int) -> bool:
    conn = store.connect()
    if conn is None:
        return False
    try:
        cursor = conn.execute("DELETE FROM corrections WHERE id = ?",
                              (int(correction_id),))
        conn.commit()
        return bool(cursor.rowcount)
    except Exception:  # noqa: BLE001
        return False


def count() -> int:
    conn = store.connect()
    if conn is None:
        return 0
    try:
        return int(conn.execute(
            "SELECT COUNT(*) AS n FROM corrections").fetchone()["n"] or 0)
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------------------
# Using them
# ---------------------------------------------------------------------------

def relevant(text: str, limit: int = MAX_SHOWN) -> list[dict]:
    """The corrections worth putting in front of the model for THIS request.

    Not all of them. The prompt already carries the persona, the date, the
    facts, the diary, the contacts, the tasks and the recall — adding every
    lesson ever learned would crowd out the thing being asked about. A lesson
    about editing reminders is only useful while a reminder is being edited.

    Matched on shared subject rather than by embedding: these are short, there
    are few of them, and a set intersection costs nothing and needs no quota.
    A taught correction outranks a noticed one at equal overlap, because one is
    something Rohan said and the other is something Jarvis guessed.
    """
    wanted = _content(text)
    if not wanted:
        return []
    scored = []
    for row in all_corrections(50):
        subject = _content(f"{row['asked']} {row['meant']}")
        shared = len(wanted & subject)
        if not shared:
            continue
        weight = shared * 10 + (6 if row["source"] == TAUGHT else 0) \
            + min(6, int(row["hits"]) * 2)
        scored.append((weight, row))
    scored.sort(key=lambda pair: -pair[0])
    return [row for _, row in scored[:limit]]


def block(text: str) -> str:
    """The relevant corrections, as a line for the system prompt."""
    found = relevant(text)
    if not found:
        return ""
    lines = []
    used = 0
    for row in found:
        if row["asked"]:
            line = f"when they say “{row['asked']}”, {row['meant']}"
        else:
            line = row["meant"]
        if used + len(line) > BLOCK_CHARS:
            break
        used += len(line)
        lines.append(line)
    if not lines:
        return ""
    return ("\n\nThings you have got wrong before and they corrected — follow "
            "these over your own instinct: " + "; ".join(lines) + ".")


def correcting_note(previous_user: str, previous_reply: str) -> str:
    """Told to the model when this turn looks like it is putting something right.

    Deliberately an instruction rather than a fact: the acknowledgement Rohan
    asked for has to actually happen, and asking the model for it in the prompt
    produces something that reads like a person, where appending a sentence
    afterwards reads like a form letter.
    """
    return ("\n\nIMPORTANT: they appear to be correcting you. Your last answer "
            f"to “{_clean(previous_user)}” was: "
            f"“{_clean(previous_reply)[:200]}” — and it was not what "
            "they wanted. Acknowledge that briefly, in a few words, then do "
            "what they are actually asking. Do not apologise at length and do "
            "not explain what went wrong.")
