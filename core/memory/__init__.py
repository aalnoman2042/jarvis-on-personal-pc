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

from core import clock
from core import config
from core.memory import agenda as _agenda_mod
from core.memory import facts as _facts_mod
from core.memory import migrate as _migrate
from core.memory import recall as _recall_mod
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

# --- what is still ahead ---------------------------------------------------
#
# Exposed as functions, not as `agenda = _agenda_mod`, on purpose: `facts` was
# bound to a function here and has shadowed the submodule of the same name twice
# now (see the note in CLAUDE.md). One trap of that shape is enough.
recalled_for = _recall_mod.describe   # what was recalled, for the screen
upcoming = _agenda_mod.upcoming
schedule_count = _agenda_mod.count
agenda_block = _agenda_mod.block
describe_item = _agenda_mod.describe

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


def system_prompt(about: str = "") -> str:
    """The persona, plus whatever Jarvis has been told to remember.

    Deliberately NOT part of config.system_prompt(): every brain reads that once
    at import, so a fact remembered mid-session wouldn't reach the model until a
    restart — and config importing memory would be a circular import.
    """
    # `about` is what was just said. Given it, the full-text index is searched
    # and anything relevant from months ago is put in front of the model —
    # otherwise it sees only the last MEMORY_TURNS exchanges, which is six, and
    # "what did I say about NILM last week" is answered by something that was
    # never shown it. Costs no API call: one indexed query against SQLite.
    #
    # Today's date matters more than it looks. Without it a model dates
    # everything from its training cut-off, so "next Thursday" lands in the
    # wrong year and nobody finds out until the reminder does not arrive.
    return (config.system_prompt()
            + f"\n\nRight now it is {clock.today_line()}."
            + facts_block()
            + agenda_block()
            + (_recall_mod.block(about, skip_recent=config.MEMORY_TURNS)
               if about else ""))


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
