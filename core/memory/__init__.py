"""Jarvis's memory — shared across brains, and surviving restarts.

Every brain's reply gets recorded here, whichever brain produced it. That's the
point: when Groq's daily free tier runs out mid-conversation and another brain
takes over, the new one can still see what was already said. Without this, each
brain kept its own private history and handing over meant starting blank —
"my favourite colour is green" answered by Groq, then "what's my favourite
colour?" answered by the next brain with "you haven't told me yet".

Only plain user/assistant TEXT is stored — never the tool-call scaffolding.
Providers disagree wildly about how tool calls are shaped (Groq keys results by
id, Ollama by name, Gemini and Claude use their own objects entirely), and none
of that has to survive a turn. Keeping only what was actually *said* sidesteps
all of it, and means a trimmed history can never orphan a tool result from the
call it belongs to — which providers reject outright.

Costs nothing while Jarvis sits idle: there is NO background thread and NO timer
here, deliberately. One small write when a turn finishes, one indexed read when
a question is asked. Please keep it that way.

**This module is the public face.** Storage lives in `store`, the remembered
notes in `facts`, and the one-time import from v1's files in `migrate`. Callers
should keep using `memory.add_turn(...)`, `memory.wrap(brain)` and friends and
never reach past this file — that indirection is what let the switch from flat
files to SQLite happen without touching a single brain.
"""
from __future__ import annotations

from core import config
from core.memory import facts as _facts_mod
from core.memory import migrate as _migrate
from core.memory import store

# --- storage, re-exported -------------------------------------------------
add_turn = store.add_turn
recent = store.recent
clear = store.clear
search = store.search
count = store.count
log_action = store.log_action
recent_actions = store.recent_actions
DB_FILE = store.DB_FILE

# --- remembered notes, re-exported under their v1 names -------------------
facts = _facts_mod.facts
add_fact = _facts_mod.add
forget_fact = _facts_mod.forget
facts_block = _facts_mod.block

# --- where v1 kept things, for anything that still refers to them ---------
HISTORY_FILE = _migrate.HISTORY_FILE
FACTS_FILE = _migrate.FACTS_FILE

MAX_TEXT = store.MAX_TEXT     # characters stored per message
INJECT_CHARS = 400            # characters of each message actually sent to a model


def load() -> None:
    """Open the database and run the one-time import from v1's files.

    v1 called this to read the tail of a text file at startup. There is nothing
    to preload now — SQLite reads what it needs when asked — so this only warms
    the connection. Kept because callers still call it, and because it is a
    natural place to fail early if the database cannot be opened at all.
    """
    store.connect()


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
    isn't enough for a small model: six long exchanges can outgrow its whole
    context, and when that happens the oldest thing in the window — the persona —
    is what gets pushed out.

    Note this trims what is *sent*, not what is *stored*. The database keeps
    everything; this decides how much of it a given model sees this turn.
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
