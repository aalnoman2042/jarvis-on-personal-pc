"""Searching everything Jarvis knows, in one list.

The conversation has a full-text index. The facts, the diary, the tasks, the
people and the action log do not, and never will — a few dozen rows each are
cheap to scan, and an index on every one of them would be five more things to
keep honest for no gain.

**bm25 is a shortlist, not a score.** FTS5 ranks messages against each other
perfectly well and against nothing else at all: the numbers are negative,
corpus-dependent and unbounded, so putting one beside "this fact contains two
of your three words" produces an order that shifts as the archive grows and
cannot be explained to the person reading it. So MATCH decides which messages
are worth looking at, its rank is thrown away, and every candidate from every
store is scored again by one function on one scale.

**SQL is broad, Python is strict.** `LIKE '%ai%'` matches "said"; FTS5 folds
"Café" to "cafe". Both are fine, because nothing is returned on the strength of
a SQL match — the scorer re-checks every candidate on folded, word-boundary
terms, so the six stores cannot disagree about what matched. That asymmetry is
exactly the bug that made recall silently drop rows the index had correctly
found.

Costs no API calls. It is SQL and string comparison. Document passages are
in here on the same terms as everything else — a paper you filed should turn
up beside the conversation where you talked about it, not in a separate
place you have to remember to look.
"""
from __future__ import annotations

import re

from core import clock
from core.memory import recall, store

# Candidates taken from each store before scoring. Generous: the scorer is what
# decides, and starving it produces confident nonsense.
PER_STORE = 40
LIMIT = 25
SNIP = 160

KINDS = ("message", "fact", "diary", "task", "person", "action", "passage")


def _fold(text: str) -> str:
    return recall._fold(text or "")


def _score(terms: list[str], title: str, body: str, when: float) -> int:
    """One scale for every store, which is what makes them sortable together."""
    ftitle, fbody = _fold(title), _fold(body)
    hits = 0
    in_title = 0
    for term in terms:
        # Word boundary, not substring: "ai" must not match "said". Long words
        # get a substring escape hatch so "dataset" still finds "datasets".
        pattern = r"\b" + re.escape(term)
        if re.search(pattern, ftitle):
            hits += 1
            in_title += 1
        elif re.search(pattern, fbody):
            hits += 1
        elif len(term) >= 5 and (term in ftitle or term in fbody):
            hits += 1
    if not hits:
        return 0
    points = hits * 10 + in_title * 6
    # Every term present is worth a lot more than most of them.
    if hits == len(terms):
        points += 12
    # Density. A single-word query matches everything equally otherwise, and
    # every result ties at the same number — so "NILM" cannot tell the fact
    # that IS about NILM from a long message that mentions it once. A short
    # field holding the term is a more concentrated hit than a long one.
    length = len(ftitle) + len(fbody)
    if length:
        points += min(8, int(sum(len(t) for t in terms) * 40 / max(length, 1)))

    # A nudge for recency, never enough to outrank a better match.
    if when:
        age_days = max(0.0, (clock.now() - when) / 86400)
        points += 4 if age_days < 7 else 2 if age_days < 60 else 0
    return points


def _window(text: str, terms: list[str]) -> str:
    """A readable slice of a long passage, centred on what matched.

    Showing the first 160 characters of a paragraph is showing its opening
    clause, which is rarely the reason it came back. A hit you have to open to
    understand is barely a hit.
    """
    flat = " ".join((text or "").split())
    if len(flat) <= SNIP:
        return flat
    folded = _fold(flat)
    at = -1
    for term in terms:
        found = re.search(r"\b" + re.escape(term), folded)
        if found:
            at = found.start()
            break
    if at < 0:
        return flat[:SNIP] + "\u2026"
    start = max(0, at - SNIP // 3)
    # Start at a word boundary, or the snippet opens mid-word and reads as
    # corruption rather than as an excerpt.
    if start:
        space = flat.find(" ", start)
        start = space + 1 if 0 <= space < start + 20 else start
    piece = flat[start:start + SNIP].strip()
    return ("\u2026" if start else "") + piece + ("\u2026" if start + SNIP < len(flat) else "")


def _rows(sql: str, args: tuple) -> list[dict]:
    conn = store.connect()
    if conn is None:
        return []
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    except Exception:  # noqa: BLE001
        return []


def search(query: str, limit: int = LIMIT) -> list[dict]:
    """Everything matching, best first, across all six stores."""
    terms = recall.terms(query)
    if not terms:
        # A query of nothing but stopwords would otherwise LIKE-match the whole
        # database and rank the noise.
        return []
    like = f"%{_fold(query).strip()}%"
    found: list[dict] = []

    # --- the conversation, via the index ---------------------------------
    fts = store.search(recall.query_for(query), limit=PER_STORE)
    for row in fts:
        found.append({
            "kind": "message", "id": 0, "when": row.get("ts", 0),
            "title": (row.get("user") or "")[:SNIP],
            "body": (row.get("assistant") or "")[:SNIP],
        })

    # --- everything else, by plain scan ----------------------------------
    for row in _rows("SELECT id, ts, fact FROM facts WHERE lower(fact) LIKE ? LIMIT ?",
                     (like, PER_STORE)):
        found.append({"kind": "fact", "id": row["id"], "when": row["ts"],
                      "title": row["fact"], "body": ""})

    for row in _rows(
        "SELECT id, due, message, kind, all_day FROM reminders "
        "WHERE lower(message) LIKE ? ORDER BY due DESC LIMIT ?", (like, PER_STORE)):
        found.append({"kind": "diary", "id": row["id"], "when": row["due"],
                      "title": row["message"],
                      "body": clock.say(row["due"], bool(row["all_day"]))})

    for row in _rows(
        "SELECT id, text, created, done, due FROM tasks "
        "WHERE lower(text) LIKE ? ORDER BY created DESC LIMIT ?", (like, PER_STORE)):
        found.append({"kind": "task", "id": row["id"], "when": row["created"],
                      "title": row["text"],
                      "body": "done" if row["done"] else "still to do"})

    for row in _rows(
        "SELECT id, name, note, created FROM contacts "
        "WHERE lower(name) LIKE ? OR lower(note) LIKE ? LIMIT ?",
        (like, like, PER_STORE)):
        found.append({"kind": "person", "id": row["id"], "when": row["created"],
                      "title": row["name"], "body": row["note"] or ""})

    for row in _rows(
        "SELECT id, ts, tool, args, result FROM action_log "
        "WHERE lower(tool) LIKE ? OR lower(args) LIKE ? ORDER BY ts DESC LIMIT ?",
        (like, like, PER_STORE)):
        found.append({"kind": "action", "id": row["id"], "when": row["ts"],
                      "title": (row["tool"] or "").replace("_", " "),
                      "body": (row["args"] or "")[:SNIP]})

    for row in _rows(
        "SELECT c.id, c.text, d.name, d.added FROM doc_chunks c "
        "JOIN documents d ON d.id = c.doc_id "
        "WHERE lower(c.text) LIKE ? OR lower(d.name) LIKE ? LIMIT ?",
        (like, like, PER_STORE)):
        # Title is the document, body is the passage. That way a hit says WHERE
        # it came from before it says what it said, which is most of what you
        # want to know when a search returns a paragraph out of a paper.
        found.append({"kind": "passage", "id": row["id"], "when": row["added"],
                      "title": row["name"],
                      "body": _window(row["text"] or "", terms),
                      "full": row["text"] or ""})

    for item in found:
        # Scored on `full` where there is one. Truncating BEFORE scoring is the
        # same asymmetry this module exists to avoid, just pointing the other
        # way: SQL matched the whole passage, the scorer saw the first 160
        # characters, and anything whose match sat further in was found and then
        # silently thrown away. Documents made that systematic — a passage is
        # 900 characters, so most of every one of them was invisible.
        item["score"] = _score(terms, item["title"],
                               item.get("full") or item["body"], item["when"])
        item.pop("full", None)

    # A zero means the SQL matched and the scorer did not agree — a LIKE hit
    # inside a longer word, most often. Dropping those is what keeps the list
    # honest; a search that returns rubbish is worse than one that returns
    # nothing, because you stop trusting the good results too.
    kept = [i for i in found if i["score"] > 0]
    kept.sort(key=lambda i: (-i["score"], -(i["when"] or 0)))
    return kept[:limit]


def summary(query: str) -> dict:
    """Counts by kind, for a screen that shows where the matches are."""
    results = search(query, limit=200)
    counts = {k: 0 for k in KINDS}
    for item in results:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return {"total": len(results), "by_kind": counts}
