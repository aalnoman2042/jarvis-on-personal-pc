"""Reaching past the last six exchanges.

The database has held everything ever said since phase 01, and a full-text
index over it since the same day. Nothing ever called it. Every turn, the model
saw `recent(MEMORY_TURNS)` — six exchanges — and nothing else, so "what did I
say about NILM last week?" was answered by a model that had never been shown it.
The memory was there; the *retrieval* was not, and without retrieval a personal
assistant is a chatbot with a good filing cabinet it never opens.

**The query is the whole job.** `store.search` hands its argument straight to
FTS5, and FTS5 reads a bare list of words as "every one of these must appear".
So "what did I say about NILM" asks for messages containing *what* AND *did* AND
*I* AND *say* AND *about* AND *NILM* — which is essentially never, and the
occasional punctuation error is swallowed into an empty list. Wiring it up
without fixing that would have looked like it worked and returned nothing
forever.

**It costs no API calls.** One indexed SQLite query per turn. That is the point:
the expensive part of a personal assistant should be the reasoning, not the
remembering.
"""
from __future__ import annotations

import re
import unicodedata

from core import clock
from core.memory import store

# Words that carry no meaning for retrieval and, worse, match everything. Kept
# deliberately short: over-trimming a question down to nothing is a worse
# failure than leaving a common word in, because one returns nothing at all.
STOPWORDS = {
    "a", "about", "after", "again", "all", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "but", "by", "can",
    "could", "did", "do", "does", "doing", "done", "for", "from", "get", "got",
    "had", "has", "have", "he", "her", "here", "him", "his", "how", "i", "if",
    "in", "into", "is", "it", "its", "just", "know", "like", "me", "mine",
    "more", "most", "my", "no", "not", "now", "of", "on", "one", "or", "our",
    "out", "over", "please", "said", "say", "she", "should", "so", "some",
    "tell", "than", "that", "the", "their", "them", "then", "there", "these",
    "they", "this", "to", "told", "too", "up", "us", "was", "we", "were",
    "what", "when", "where", "which", "who", "why", "will", "with", "would",
    "you", "your", "yours", "am", "remember", "recall",
}

# A word shorter than this is noise in an index this size.
MIN_WORD = 3
# More than this and the OR query matches half the database.
MAX_TERMS = 8
# How many past exchanges to consider before trimming.
MAX_HITS = 6
# Characters of recalled material allowed into the prompt. Separate from the
# recent-history budget on purpose: a big recall must never be able to push the
# persona out of a small model's context.
MAX_CHARS = 1200
# Characters kept from each side of a recalled exchange.
SNIP = 260


def _fold(text: str) -> str:
    """Lowercase and strip accents, the way FTS5's unicode61 tokenizer does.

    The index and anything that second-guesses the index have to agree about
    what a word is. They did not: "résumé" is indexed as "resume", so a search
    for "resume" found the row and the relevance check — a plain substring test
    on the raw text — then discarded it.
    """
    flat = unicodedata.normalize("NFKD", text or "").lower()
    return "".join(ch for ch in flat if not unicodedata.combining(ch))


def terms(text: str) -> list[str]:
    """The words worth searching for, in the order they were said.

    Everything non-alphanumeric goes, which doubles as the FTS5 escaping: what
    is left cannot contain a quote, a hyphen, or an operator like NEAR, so the
    query cannot be malformed by punctuation the way the raw sentence could.
    """
    words = re.findall(r"[a-z0-9]+", _fold(text))
    picked: list[str] = []
    for word in words:
        if len(word) < MIN_WORD or word in STOPWORDS or word in picked:
            continue
        picked.append(word)
        if len(picked) >= MAX_TERMS:
            break
    return picked


def query_for(text: str) -> str:
    """An FTS5 query that finds things rather than nothing.

    OR, not the implicit AND: someone asking about "the CNN LSTM comparison"
    should reach an exchange that mentioned only LSTM. Ranking sorts out which
    matches were good — that is what bm25 is for — so breadth here costs
    nothing and narrowness costs everything.
    """
    picked = terms(text)
    return " OR ".join(picked) if picked else ""


# Verbs that begin an instruction rather than a question. "Open youtube" wants a
# tool, not a memory, and searching for it drags in every past "open calculator"
# as though it were relevant — noise that costs budget and makes the recall
# readout look broken. A question about the past is what this is for.
COMMAND_VERBS = {
    "open", "close", "quit", "kill", "launch", "start", "run", "play", "pause",
    "stop", "skip", "next", "previous", "lock", "shutdown", "restart", "reboot",
    "turn", "set", "mute", "volume", "screenshot", "take", "call", "message",
    "text", "navigate", "go", "send", "write", "make", "create", "add",
    "cancel", "delete", "remove", "forget",
}


def looks_like_a_command(text: str) -> bool:
    """True when this is an instruction, so recall should stay out of the way."""
    words = re.findall(r"[a-z']+", (text or "").lower())
    if not words:
        return True
    # An instruction leads with its verb. "Hey Jarvis, open chrome" leads with
    # the wake word, so a couple of opening words are looked past.
    for word in words[:3]:
        if word in COMMAND_VERBS:
            return True
    return False


def find(text: str, skip_recent: int = 0, limit: int = MAX_HITS) -> list[dict]:
    """Past exchanges worth showing the model, best first.

    `skip_recent` drops anything already inside the rolling window the model can
    see anyway — recalling the message directly above the question wastes the
    budget and reads as a stutter.
    """
    if looks_like_a_command(text):
        return []
    query = query_for(text)
    if not query:
        return []

    wanted = terms(text)
    # Keyword hits, filtered by the word floor as they always have been.
    by_word = [h for h in store.search(query, limit=limit + skip_recent + 4)
               if _relevant(h, wanted)]

    # And the ones no keyword could have found. This is the whole point: "what
    # did I say about power disaggregation" shares not one word with the
    # conversation that answers it, so the word floor above would refuse it —
    # correctly, on the evidence it has. A meaning hit clears a different bar,
    # measured in core/memory/vectors.py, and is trusted on that instead.
    by_meaning = _by_meaning(text, limit)

    kept = _interleave(by_word, by_meaning)

    if skip_recent:
        recent = store.recent(skip_recent)
        seen = {(r.get("ts"), (r.get("user") or "")[:60]) for r in recent}
        kept = [h for h in kept
                if (h.get("ts"), (h.get("user") or "")[:60]) not in seen]

    return kept[:limit]


def _same(a: dict, b: dict) -> bool:
    return (a.get("ts") == b.get("ts")
            and (a.get("user") or "")[:60] == (b.get("user") or "")[:60])


def _interleave(by_word: list[dict], by_meaning: list[dict]) -> list[dict]:
    """One list from two searches, taking turns.

    NOT one after the other, which is what this did first and was wrong. The
    keyword list is longer and arrives first, so appending meaning hits behind
    it buried the good one: asked about "power disaggregation", the prompt led
    with an exchange that merely contained the word "power" and pushed the
    conversation actually about the subject down past the character budget.

    Taking turns is the honest arrangement, because there is no shared scale to
    sort by. bm25 and cosine measure different things in different units — the
    mistake `find.py` exists to warn about — so neither list can be declared
    better than the other. What can be said is that each is ordered well within
    itself, and that a hit only one of them found is exactly the hit worth
    keeping. Alternating preserves both orderings and lets neither starve the
    other.
    """
    out: list[dict] = []
    for pair in zip(by_word, by_meaning):
        for hit in pair:
            if not any(_same(hit, seen) for seen in out):
                out.append(hit)
    for rest in (by_word[len(by_meaning):], by_meaning[len(by_word):]):
        for hit in rest:
            if not any(_same(hit, seen) for seen in out):
                out.append(hit)
    return out


def _by_meaning(text: str, limit: int, kinds: tuple = ("message",)) -> list[dict]:
    """Exchanges close in meaning, whatever words they used.

    Imported here rather than at module level: `vectors` reaches back into this
    module for the stopword list and the folding, and importing it at the top
    would be a cycle. It is also the honest shape — meaning-based recall is an
    optional extra over keyword recall, and this file must keep working when it
    is not there at all.
    """
    try:
        from core.memory import vectors
    except Exception:  # noqa: BLE001
        return []
    rows = [r for r in vectors.search(text, limit=limit * 2)
            if r["kind"] in kinds][:limit]
    if not rows:
        return []
    conn = store.connect()
    if conn is None:
        return []
    out: list[dict] = []
    for row in rows:
        try:
            if row["kind"] == "message":
                got = conn.execute(
                    "SELECT ts, user, assistant FROM messages WHERE id = ?",
                    (row["id"],)).fetchone()
            elif row["kind"] == "fact":
                got = conn.execute(
                    "SELECT ts, fact FROM facts WHERE id = ?",
                    (row["id"],)).fetchone()
            else:
                continue
        except Exception:  # noqa: BLE001
            continue
        if got:
            hit = dict(got)
            hit["similarity"] = row["similarity"]
            out.append(hit)
    return out


def remembered_facts(text: str, already: str = "", limit: int = 2) -> list[str]:
    """Facts close in meaning to the question that are NOT already in the prompt.

    `facts.block()` is capped by rendered length because it is re-sent with every
    single question, so once enough has been remembered the older half stops
    being shown at all. Those are exactly the ones worth pulling back when they
    become relevant — and until this existed they were embedded, stored and paid
    for, then dropped on the way out because the retrieval only looked at
    messages.

    `already` is the block that has been built, so nothing is said twice.
    """
    if looks_like_a_command(text):
        return []
    seen = _fold(already)
    out: list[str] = []
    for hit in _by_meaning(text, limit + 3, kinds=("fact",)):
        fact = (hit.get("fact") or "").strip()
        if not fact or _fold(fact.rstrip(".")) in seen:
            continue
        out.append(fact.rstrip("."))
        if len(out) >= limit:
            break
    return out


def _relevant(hit: dict, wanted: list[str]) -> bool:
    """Does this hit actually answer to the question, or did one word land?

    `OR` is what makes retrieval find anything at all, and it is also what makes
    it find rubbish: a search for "supervisor compare CNN" will happily return
    an unrelated exchange whose *reply* happened to contain "compare". Ranking
    puts the good hit first but does not stop the bad one being included, and a
    recalled irrelevance is worse than a recall that came back empty — it is
    noise in the prompt and a lie on the recall readout.
    """
    if not wanted:
        return False
    # Folded, not merely lowercased. FTS5's unicode61 tokenizer strips accents,
    # so a search for "resume" genuinely matches "résumé" — and this filter,
    # doing a plain substring test, then threw the row away. The index was
    # right and the guard overruled it, which is the worst shape of bug: the
    # data was found and then discarded, so it looked like nothing was there.
    haystack = _fold(f"{hit.get('user', '')} {hit.get('assistant', '')}")
    matched = sum(1 for term in wanted if term in haystack)
    # One word is enough to go on when that word was most of the question.
    # Past that, a single incidental match is not evidence of anything.
    need = 1 if len(wanted) <= 2 else 2
    return matched >= need


def block(text: str, skip_recent: int = 0) -> str:
    """The recalled exchanges as a paragraph for the system prompt.

    Goes in the system message rather than as extra turns. Providers reject a
    history that does not strictly alternate, and injecting old exchanges as
    real messages is the fastest way to build one that does not — the same
    reasoning that keeps tool-call scaffolding out of storage entirely.

    Dated, because "you said this in July" and "you said this an hour ago" mean
    very different things and a model given neither will guess.
    """
    hits = find(text, skip_recent=skip_recent)
    if not hits:
        return ""

    lines: list[str] = []
    used = 0
    for hit in hits:
        when = clock.was(hit["ts"]) if hit.get("ts") else "earlier"
        said = " ".join((hit.get("user") or "").split())[:SNIP]
        replied = " ".join((hit.get("assistant") or "").split())[:SNIP]
        if not said:
            continue
        line = f"- {when}, they said: {said}"
        if replied:
            line += f" | you answered: {replied}"
        if used + len(line) > MAX_CHARS:
            break
        used += len(line)
        lines.append(line)

    if not lines:
        return ""
    return ("\n\nFrom earlier conversations, possibly relevant (do not mention "
            "these unless they help; they are recalled, not just said):\n"
            + "\n".join(lines))


def describe(text: str, skip_recent: int = 0) -> list[dict]:
    """What was recalled, for showing on screen rather than telling the model.

    The HUD lists these so a wrong answer can be told apart from a wrong recall.
    Without it, "it got that wrong" has two possible causes and no way to
    separate them.
    """
    return [
        {
            "when": hit["ts"],
            "said": " ".join((hit.get("user") or "").split())[:120],
        }
        for hit in find(text, skip_recent=skip_recent)
    ]
