"""Jarvis's memory of the conversation — shared, and surviving restarts.

Every brain's reply gets recorded here, whichever brain produced it. That's the
point: when Groq's daily free tier runs out mid-conversation and the local model
takes over, the local model can still see what was already said. Without this,
each brain kept its own private history and handing over meant starting blank —
"my favourite colour is green" answered by Groq, then "what's my favourite
colour?" answered by the local model with "you haven't told me yet".

Only plain user/assistant TEXT is stored — never the tool-call scaffolding.
Providers disagree wildly about how tool calls are shaped (Groq keys results by
id, Ollama by name, Gemini and Claude use their own objects entirely), and none
of that has to survive a turn. Keeping only what was actually *said* sidesteps
all of it, and means a trimmed history can never orphan a tool result from the
call it belongs to — which providers reject outright.

Costs nothing while Jarvis sits idle: there is NO background thread and NO
timer here, deliberately. One small append when a turn finishes, one read at
startup. Please keep it that way.
"""
from __future__ import annotations

import json
import os
import threading
import time

from core import config

HISTORY_FILE = os.path.join(config.PROJECT_DIR, "jarvis.history.jsonl")
FACTS_FILE = os.path.join(config.PROJECT_DIR, "jarvis.facts.json")

MAX_TURNS_RAM = 200      # exchanges held in memory at once
MAX_TEXT = 1000          # characters stored per message
INJECT_CHARS = 400       # characters of each message actually sent to a model
TAIL_BYTES = 64 * 1024   # how much of the end of the file to read at startup
COMPACT_BYTES = 1_000_000

_lock = threading.Lock()
_turns: list[dict] = []   # {"ts": float, "brain": str, "user": str, "assistant": str}
_loaded = False

_facts_lock = threading.Lock()
_facts: list[str] = []
_facts_loaded = False


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _parse_lines(blob: str) -> list[dict]:
    """Turn raw file text into records, skipping anything unreadable.

    A half-written line (two copies of Jarvis running, or a power cut mid-write)
    costs exactly that one exchange instead of the whole file. This is the entire
    reason the history is one-JSON-object-per-line rather than a single document.
    """
    out = []
    for line in blob.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:  # noqa: BLE001  (malformed line — skip just this one)
            continue
        if isinstance(rec, dict) and "user" in rec and "assistant" in rec:
            out.append(rec)
    return out


def load() -> None:
    """Read recent history off disk. Safe to call repeatedly; never raises.

    Only the tail of the file is read, so startup stays instant no matter how
    long Jarvis has been talking to you.
    """
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        if not config.MEMORY_ENABLED:
            return
        try:
            size = os.path.getsize(HISTORY_FILE)
            with open(HISTORY_FILE, "rb") as f:
                if size > TAIL_BYTES:
                    f.seek(size - TAIL_BYTES)
                    f.readline()  # drop the partial line we landed in the middle of
                blob = f.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001  (missing/unreadable — start fresh)
            return
        _turns.extend(_parse_lines(blob)[-MAX_TURNS_RAM:])
    if size > COMPACT_BYTES:
        _compact()


def _compact() -> None:
    """Rewrite the file with just the exchanges we still keep in memory.

    Only ever called at startup — never on a timer, so Jarvis stays at zero CPU
    while idle.
    """
    tmp = HISTORY_FILE + ".tmp"
    try:
        with _lock:
            keep = list(_turns)
        with open(tmp, "w", encoding="utf-8") as f:
            for rec in keep:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp, HISTORY_FILE)  # atomic, so a crash can't leave a half file
    except Exception:  # noqa: BLE001
        try:
            os.remove(tmp)
        except OSError:
            pass


def add_turn(user: str, assistant: str, brain: str = "") -> None:
    """Record one finished exchange. Never raises — memory must not break Jarvis."""
    if not config.MEMORY_ENABLED:
        return
    user, assistant = (user or "").strip(), (assistant or "").strip()
    if not user or not assistant:
        return
    rec = {
        "ts": round(time.time(), 1),
        "brain": brain,
        "user": user[:MAX_TEXT],
        "assistant": assistant[:MAX_TEXT],
    }
    with _lock:
        _turns.append(rec)
        del _turns[:-MAX_TURNS_RAM]
        try:
            # Appended as the turn ends, not saved on exit: stop_jarvis.bat kills
            # the process outright, so anything held back until shutdown is lost.
            with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001  (disk full, permissions — keep talking)
            pass


def recent(limit: int | None = None) -> list[dict]:
    """The most recent exchanges, oldest first."""
    load()
    with _lock:
        turns = list(_turns)
    if limit is not None and limit >= 0:
        turns = turns[-limit:] if limit else []
    return turns


def clear() -> None:
    """Forget everything, in memory and on disk."""
    with _lock:
        _turns.clear()
        try:
            os.remove(HISTORY_FILE)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Things worth keeping for good
#
# The conversation above is a rolling window — say something twenty turns ago
# and it's gone. Facts are the opposite: short notes that ride along with every
# question, for good. "Rohan works night shifts." "Rohan's sister is Ayesha."
#
# They're capped hard, by rendered size rather than count, because unlike the
# conversation these are re-sent on EVERY request to every brain. A list that
# grew without limit would quietly eat the daily free cloud allowance.
# ---------------------------------------------------------------------------

def _load_facts() -> None:
    """Read the facts file. Safe to call repeatedly; never raises."""
    global _facts_loaded
    with _facts_lock:
        if _facts_loaded:
            return
        _facts_loaded = True
        if not config.MEMORY_ENABLED:
            return
        try:
            with open(FACTS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001  (missing/corrupt — start with none)
            return
        if isinstance(data, list):
            _facts.extend(str(x).strip() for x in data if str(x).strip())


def _save_facts() -> None:
    """Write the facts file atomically. Caller holds _facts_lock."""
    tmp = FACTS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_facts, f, ensure_ascii=False, indent=1)
        os.replace(tmp, FACTS_FILE)  # never leaves a half-written file behind
    except Exception:  # noqa: BLE001
        try:
            os.remove(tmp)
        except OSError:
            pass


def facts() -> list[str]:
    """Everything Jarvis has been told to remember."""
    _load_facts()
    with _facts_lock:
        return list(_facts)


def _third_person(fact: str) -> str:
    """Rewrite "your birthday is..." as "Rohan's birthday is...".

    Facts get read back to the model as notes *about* the user, so a fact stored
    as "you" or "I" reads as being about the wrong person. Small models write it
    either way whatever the tool description asks, so fix it here instead.
    """
    who = config.USER_TITLE or "the user"
    swaps = (
        ("your ", f"{who}'s "), ("you're ", f"{who} is "), ("you are ", f"{who} is "),
        ("you ", f"{who} "), ("my ", f"{who}'s "), ("i'm ", f"{who} is "),
        ("i am ", f"{who} is "), ("i ", f"{who} "),
    )
    low = fact.lower()
    for prefix, replacement in swaps:
        if low.startswith(prefix):
            return replacement + fact[len(prefix):]
    return fact


def add_fact(fact: str) -> str:
    """Remember something for good. Returns a line to say back."""
    fact = " ".join((fact or "").split())  # collapse dictated whitespace
    fact = _third_person(fact)
    if not fact:
        return "There was nothing to remember."
    if not config.MEMORY_ENABLED:
        return "My memory is switched off at the moment."
    _load_facts()
    with _facts_lock:
        if any(fact.lower() == existing.lower() for existing in _facts):
            return "I already had that one."
        _facts.append(fact)
        # Oldest go first when it's full — the newest thing you said matters most.
        del _facts[:-config.MEMORY_MAX_FACTS]
        _save_facts()
    return f"Noted. I'll remember that {fact.rstrip('.')}."


def forget_fact(fragment: str) -> str:
    """Drop remembered things matching a fragment. Returns a line to say back."""
    fragment = " ".join((fragment or "").split()).lower()
    if not fragment:
        return "Tell me what to forget."
    _load_facts()
    with _facts_lock:
        if fragment in ("all", "everything"):
            count = len(_facts)
            _facts.clear()
            _save_facts()
            return f"Forgotten, all {count} of them." if count else "There was nothing to forget."
        keep = [f for f in _facts if fragment not in f.lower()]
        dropped = len(_facts) - len(keep)
        if not dropped:
            return f"I had nothing remembered about {fragment}."
        _facts[:] = keep
        _save_facts()
    return f"Forgotten. That's {dropped} thing{'s' if dropped > 1 else ''} about {fragment}."


def facts_block() -> str:
    """The facts as a line for the system prompt, or '' when there are none.

    Capped by rendered length, since this is re-sent with every single question.
    """
    kept, used = [], 0
    for fact in facts():
        line = fact.rstrip(".")
        if used + len(line) + 2 > config.MEMORY_FACTS_CHARS:
            break
        kept.append(line)
        used += len(line) + 2
    if not kept:
        return ""
    return (" Things you already know about them, remembered from earlier: "
            + "; ".join(kept) + ". Use these when relevant without mentioning "
            "that you looked them up.")


def system_prompt() -> str:
    """The persona, plus whatever Jarvis has been told to remember.

    Deliberately NOT part of config.system_prompt(): every brain reads that once
    at import, so a fact remembered mid-session wouldn't reach the model until a
    restart — and config importing memory would be a circular import.
    """
    return config.system_prompt() + facts_block()


# ---------------------------------------------------------------------------
# Shaping history for a model
# ---------------------------------------------------------------------------

def as_openai(system: str, user: str, limit: int | None = None,
              max_chars: int | None = None) -> list[dict]:
    """Build a message list: system prompt, past exchanges, then what was just said.

    The shape OpenAI-style APIs expect, which covers both the local model and
    Groq. Always starts with the system message and strictly alternates after it,
    so it can't produce the malformed histories providers reject.

    `max_chars` caps the total size of the replayed history. A turn count alone
    isn't enough for the local model: six long exchanges can outgrow its whole
    context, and when that happens the oldest thing in the window — the persona —
    is what gets pushed out.
    """
    if limit is None:
        limit = config.MEMORY_TURNS
    history, used = [], 0
    for rec in reversed(recent(limit)):  # newest first, so the oldest drop off
        past_user = (rec.get("user") or "").strip()[:INJECT_CHARS]
        past_reply = (rec.get("assistant") or "").strip()[:INJECT_CHARS]
        if not past_user or not past_reply:
            continue  # a half-recorded exchange would break the alternation
        if max_chars is not None and used + len(past_user) + len(past_reply) > max_chars:
            break
        used += len(past_user) + len(past_reply)
        history.append({"role": "assistant", "content": past_reply})
        history.append({"role": "user", "content": past_user})
    history.reverse()
    return ([{"role": "system", "content": system}] + history
            + [{"role": "user", "content": user}])


# ---------------------------------------------------------------------------
# Recording, without every brain having to know about it
# ---------------------------------------------------------------------------

class RememberingBrain:
    """Wraps a brain and quietly records what was said.

    Sits around the whole fallback chain, so it records one exchange per
    question no matter which brain in the chain ended up answering.
    """

    def __init__(self, brain) -> None:
        self._brain = brain
        self.name = getattr(brain, "name", "brain")

    def greeting(self) -> str:
        return self._brain.greeting()

    def handle(self, text: str) -> str:
        # Order matters: the brain reads history at the start of its own handle(),
        # and we only write once it has answered. Recording before the call would
        # show the model its own question twice.
        reply = self._brain.handle(text)
        if reply and reply != "__EXIT__":
            add_turn(text, reply, brain=self.name.split("+")[0])
        return reply


def wrap(brain):
    """Give a brain (or a whole fallback chain) a memory."""
    return RememberingBrain(brain) if config.MEMORY_ENABLED else brain
