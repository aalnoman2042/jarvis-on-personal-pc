"""Finding things by meaning, when the words do not match.

`recall.py` searches with FTS5, which is keyword matching however carefully the
query is built. Ask *"what did I say about power disaggregation"* and it finds
nothing, because the conversation said "NILM" — the right answer is sitting in
the archive with not one word in common. That is not a tuning problem; it is
what keyword search is.

So every message, every fact and every passage of every filed document also
gets an embedding, and a query is compared against those by cosine. FTS5 is not replaced: the two find different things and
both are shortlists into the same ranking, exactly as `find.py` treats bm25.

Four decisions worth keeping:

**The batch size is discovered, not assumed.** The free embedding tier is
metered on content: a single-word request succeeds in the same minute a
seven-thousand-character one is refused. So a refused batch is halved and
retried rather than abandoned — a refusal for being too large and a refusal for
having nothing left are indistinguishable from here, and treating the first as
the second stalls the whole archive until somebody notices. A tight budget
should mean slower progress, not no progress.

**Nothing is embedded on the write path.** `add_turn` must not grow an API call
— a turn would then wait on Google to store a sentence, and an embedding outage
would become a memory outage. Rows are filled in afterwards by `backfill()`,
which the server's existing sweeper and `/tick` both call. A message said ten
seconds ago is not yet in the index and does not need to be: `recent()` already
puts it in front of the model.

**The floor is measured, not guessed, and short junk is never indexed.**
Gemini's embeddings sit high: two texts about nothing in common still score
~0.52, so "similarity above a half" recalls rubbish on every query. Measured
against Rohan's actual archive, real matches land at 0.68-0.74 — hence 0.65.

That measurement also turned up the shape of the near-miss. A short vague
message — "what is", "example", "open it" — is semantically near *everything*,
so it drifts up unrelated queries: "anything about my schedule" pulled "what is"
back at 0.62. The floor is what stops those, and measurably does: across a set
of deliberately off-topic questions asked against the real archive, every one
returns nothing at all.

`worth_embedding` is a second, cheaper line — it keeps commands and fragments
out of the index in the first place, which saves the API call and the storage
rather than saving the precision. Do not confuse the two jobs. If it lets
something through, the floor still has to hold; it is the floor that is load
bearing.

**The model name is stored beside the vector.** Vectors from two different
models are not comparable, and mixing them produces confident nonsense rather
than an error. A change of model invalidates the old rows instead of silently
poisoning the results.

**int8, not float32.** Quarter the stored size, which is what a cold start pays
for over HTTPS to Turso. Measured against float32 on the real archive it returns
the same rows above the floor on every query tried, with a worst-case similarity
error of 0.006. Two rows closer together than that may swap places, which is
harmless: a pair that close is a tie whichever way it is measured.

Same contract as the rest of the package: nothing here raises into a
conversation. No key, no package, no quota — every function returns empty and
recall carries on exactly as it did before this file existed.
"""
from __future__ import annotations

import base64
import logging
import re
import threading

from core import clock, config
from core.memory import store

log = logging.getLogger("vondo.vectors")

MODEL = "gemini-embedding-001"
DIMS = 768                 # 3072 is the default and four times the storage for
                           # no measured gain at this archive size
FLOOR = 0.65               # see the note above before touching this

# A lower bar when somebody has explicitly asked to search, and the difference
# is not a fudge. Automatic recall puts what it finds into the prompt UNBIDDEN,
# so a marginal hit is noise nobody asked for and a claim nobody can check. An
# explicit search is the opposite: the answer names the document it came from,
# it was asked for, and a near-miss can be read and dismissed in a second. The
# cost of being wrong is completely different, so the threshold is too.
ASKED_FLOOR = 0.55

TOP_K = 5

# How many rows one backfill pass will embed. Small on purpose: this runs inside
# /tick, which must stay a fast, harmless request.
BATCH = 24

# And a ceiling on how much TEXT goes in one request, which is the limit that
# actually bites. A batch of 24 conversation turns is a few thousand characters;
# a batch of 24 document passages is twenty thousand, and the free embedding
# tier is metered on CONTENT rather than on rows — measured: a single-word
# request succeeds while a 7,000-character one is refused in the same minute.
# Counting rows alone means the document case quietly asks for eight times as
# much as the message case and is refused for it.
MAX_BATCH_CHARS = 6000

# The smallest batch worth trying. Below this, a refusal means the budget is
# genuinely gone rather than the request being too large.
MIN_BATCH_CHARS = 700

# What size last worked. Free-tier limits are not published in a form worth
# hard-coding and they change; discovering the size by trying is both more
# honest and self-correcting. Kept between passes so the discovery is paid for
# once rather than every sweep.
_batch_chars = MAX_BATCH_CHARS

# What stopped it, in words, or "" while nothing has. Quota exhaustion and a
# missing key look identical from the outside — both are "no vectors today" —
# and they need completely different responses from whoever is reading.
_blocked = ""
_blocked_is_quota = False

_lock = threading.Lock()
_cache: dict[tuple[str, int], object] = {}   # (kind, ref_id) -> vector
_loaded = False
_np = None
_client = None
_dead = False              # set once when embedding is known to be unavailable


def _numpy():
    """numpy, or None. Imported here so core still starts without it."""
    global _np
    if _np is None:
        try:
            import numpy
            _np = numpy
        except Exception:  # noqa: BLE001
            _np = False
    return _np or None


def _api():
    """The Gemini client, or None if it cannot be built."""
    global _client, _dead
    if _dead:
        return None
    if _client is None:
        try:
            from google import genai
            if not config.GEMINI_API_KEY:
                _dead = True
                return None
            _client = genai.Client(api_key=config.GEMINI_API_KEY)
        except Exception:  # noqa: BLE001
            _dead = True
            return None
    return _client


def available() -> bool:
    """Whether meaning-based search can work at all right now."""
    return bool(_numpy() is not None and _api() is not None)


def blocked() -> str:
    """Why nothing is being indexed, in words, or "" if all is well.

    A backlog that is not going down needs an explanation on the screen. Without
    one, "247 passages waiting" sits there for a day and reads as broken —
    when in fact it is a free tier that resets on its own and needs nothing
    from anybody.
    """
    if _numpy() is None:
        return "numpy isn't installed, so meaning-based search is off."
    if _api() is None:
        return "No Gemini key, so meaning-based search is off."
    return _blocked


def quota_exhausted() -> bool:
    return _blocked_is_quota


# ---------------------------------------------------------------------------
# Talking to the model
# ---------------------------------------------------------------------------

def embed(texts: list[str], query: bool = False) -> list[list[float] | None]:
    """Unit-length vectors for each text, or None where it did not work.

    `query` picks the asymmetric task type: Google embeds a question and the
    passage that answers it differently, and using one type for both measurably
    weakens retrieval.
    """
    global _blocked, _blocked_is_quota
    client = _api()
    texts = [(t or "").strip()[:8000] for t in texts]
    if client is None or not any(texts):
        return [None] * len(texts)
    try:
        from google.genai import types
        result = client.models.embed_content(
            model=MODEL,
            contents=[t or " " for t in texts],
            config=types.EmbedContentConfig(
                output_dimensionality=DIMS,
                task_type="RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT"),
        )
    except Exception as exc:  # noqa: BLE001
        # Quota, a withdrawn model, no network. Meaning-based search goes quiet
        # and keyword search carries the whole load, which is where it started.
        detail = str(exc)
        _blocked_is_quota = ("429" in detail or "RESOURCE_EXHAUSTED" in detail
                             or "quota" in detail.lower())
        _blocked = ("Google's free embedding quota is used up for now — "
                    "it will carry on by itself when that resets."
                    if _blocked_is_quota else
                    f"Embedding is unavailable: {detail[:120]}")
        log.info("embedding unavailable: %s", detail[:160])
        return [None] * len(texts)

    _blocked, _blocked_is_quota = "", False
    out: list[list[float] | None] = []
    for item in result.embeddings:
        values = list(item.values or [])
        # Reduced dimensions come back UNNORMALISED — only the full 3072 is a
        # unit vector. Skipping this makes cosine a dot product of different
        # magnitudes, which quietly ranks long texts above relevant ones.
        norm = sum(v * v for v in values) ** 0.5
        out.append([v / norm for v in values] if norm else None)
    while len(out) < len(texts):
        out.append(None)
    return out


# ---------------------------------------------------------------------------
# Storing them
# ---------------------------------------------------------------------------

def _pack(vec: list[float]) -> str:
    """A unit vector as base64 int8 — a quarter the size, same shortlist."""
    return base64.b64encode(
        bytes((max(-127, min(127, round(v * 127))) & 0xFF) for v in vec)).decode()


def _unpack(packed: str):
    np = _numpy()
    if np is None:
        return None
    raw = np.frombuffer(base64.b64decode(packed), dtype=np.int8)
    return raw.astype(np.float32) / 127.0


# Distinct content words an exchange needs before it is worth finding again.
# Below this it is "what is", "example", "jar" — text that means almost nothing
# and is therefore close to almost everything.
#
# Three, and the number was measured rather than picked. Four loses "when is my
# exam" and "my supervisor is Dr Haque", which are precisely the kind of thing
# this feature exists to find; two lets most of the fragments back in. Counted
# over the WHOLE exchange, not the question alone — "when is my exam" carries
# one content word by itself and three once the answer is beside it, and testing
# the question on its own threw away half of the real material.
MIN_CONTENT_WORDS = 3


def worth_embedding(user: str, assistant: str = "") -> bool:
    """Whether an exchange carries enough meaning to be findable by meaning.

    Commands are excluded for the same reason `recall` refuses to search them:
    "open youtube" wants a tool, not a memory, and indexing it drags every past
    "open calculator" into the neighbourhood of every future question. Only the
    user's half is tested for that — the reply to a command is not a command.
    """
    from core.memory import recall
    if recall.looks_like_a_command(user or ""):
        return False
    words = {w for w in re.findall(r"[a-z0-9]+", recall._fold(f"{user} {assistant}"))
             if len(w) >= 3 and w not in recall.STOPWORDS}
    return len(words) >= MIN_CONTENT_WORDS


def skip(kind: str, ref_id: int) -> None:
    """Record that a row was considered and is not worth indexing.

    An empty vector, rather than no row at all: without it every backfill pass
    would pick up the same fragments, spend the whole batch deciding to ignore
    them again, and never reach anything useful.
    """
    conn = store.connect()
    if conn is None:
        return
    try:
        conn.execute(
            "INSERT OR REPLACE INTO vectors(kind, ref_id, model, vec, ts) "
            "VALUES (?,?,?,'',?)",
            (kind, int(ref_id), MODEL, round(clock.now(), 1)))
        conn.commit()
    except Exception:  # noqa: BLE001
        pass


def save(kind: str, ref_id: int, vec: list[float]) -> None:
    conn = store.connect()
    if conn is None or not vec:
        return
    try:
        conn.execute(
            "INSERT OR REPLACE INTO vectors(kind, ref_id, model, vec, ts) "
            "VALUES (?,?,?,?,?)",
            (kind, int(ref_id), MODEL, _pack(vec), round(clock.now(), 1)))
        conn.commit()
    except Exception:  # noqa: BLE001
        return
    got = _unpack(_pack(vec))
    if got is not None:
        with _lock:
            _cache[(kind, int(ref_id))] = got


def _load_cache() -> None:
    """Read every vector once. Cheap in RAM, and it is the cold start that pays.

    Filtered by model on purpose: rows written by a previous embedding model are
    left on disk but never compared against, because a similarity between two
    different models' vectors is a number with no meaning behind it.
    """
    global _loaded
    conn = store.connect()
    if conn is None:
        return
    try:
        rows = conn.execute(
            "SELECT kind, ref_id, vec FROM vectors WHERE model = ?",
            (MODEL,)).fetchall()
    except Exception:  # noqa: BLE001
        _loaded = True
        return
    for row in rows:
        if not row["vec"]:
            continue                  # considered and deliberately not indexed
        got = _unpack(row["vec"])
        if got is not None:
            _cache[(row["kind"], int(row["ref_id"]))] = got
    _loaded = True


def _ready() -> bool:
    global _loaded
    if _loaded:
        return True
    with _lock:
        if not _loaded:
            _load_cache()
    return _loaded


# ---------------------------------------------------------------------------
# Filling in what is missing
# ---------------------------------------------------------------------------

def pending() -> int:
    """How many rows have no vector yet — for a status line, not a decision."""
    conn = store.connect()
    if conn is None:
        return 0
    try:
        row = conn.execute(
            "SELECT (SELECT COUNT(*) FROM messages m WHERE NOT EXISTS ("
            "  SELECT 1 FROM vectors v WHERE v.kind='message' AND v.ref_id=m.id"
            "  AND v.model = ?)) + "
            "(SELECT COUNT(*) FROM facts f WHERE NOT EXISTS ("
            "  SELECT 1 FROM vectors v WHERE v.kind='fact' AND v.ref_id=f.id"
            "  AND v.model = ?)) + "
            "(SELECT COUNT(*) FROM doc_chunks c WHERE NOT EXISTS ("
            "  SELECT 1 FROM vectors v WHERE v.kind='chunk' AND v.ref_id=c.id"
            "  AND v.model = ?)) AS n", (MODEL, MODEL, MODEL)).fetchone()
        return int(row["n"] or 0)
    except Exception:  # noqa: BLE001
        return 0


def backfill(limit: int = BATCH) -> int:
    """Embed some rows that have none yet. Returns how many were done.

    Newest first: what was said this week is what gets asked about, and an
    archive that fills in from the far end would take days to become useful.
    """
    conn = store.connect()
    if conn is None or not available():
        return 0
    try:
        # Facts first, and this ordering is not cosmetic. Messages outnumber
        # facts hundreds to one and arrive continuously, so a batch filled by
        # whatever is newest is a batch of messages every time — the curated
        # memory, which is the most valuable thing to be able to find, would
        # never get embedded at all. Facts are capped in number and drain in
        # one or two passes, after which messages get the whole budget.
        facts = conn.execute(
            "SELECT id, fact FROM facts f WHERE NOT EXISTS ("
            "  SELECT 1 FROM vectors v WHERE v.kind='fact' AND v.ref_id=f.id"
            "  AND v.model = ?) ORDER BY f.id DESC LIMIT ?",
            (MODEL, limit)).fetchall()
        # Passages next, for the same reason facts come first: a document was
        # put there deliberately and is useless until it is searchable, whereas
        # messages accumulate on their own and one arriving a few minutes late
        # is invisible. A freshly filed paper that cannot be found for an hour
        # reads as the filing having failed.
        passages = conn.execute(
            "SELECT id, text FROM doc_chunks c WHERE NOT EXISTS ("
            "  SELECT 1 FROM vectors v WHERE v.kind='chunk' AND v.ref_id=c.id"
            "  AND v.model = ?) ORDER BY c.id ASC LIMIT ?",
            (MODEL, max(0, limit - len(facts)))).fetchall()
        messages = conn.execute(
            "SELECT id, user, assistant FROM messages m WHERE NOT EXISTS ("
            "  SELECT 1 FROM vectors v WHERE v.kind='message' AND v.ref_id=m.id"
            "  AND v.model = ?) ORDER BY m.id DESC LIMIT ?",
            (MODEL, max(0, limit - len(facts) - len(passages)))).fetchall()
    except Exception:  # noqa: BLE001
        return 0

    jobs: list[tuple[str, int, str]] = []
    for row in facts:
        # A fact was written down deliberately, so it is always worth indexing.
        jobs.append(("fact", int(row["id"]), row["fact"]))
    for row in passages:
        # So was a document. Chunking already dropped the furniture, and a
        # passage that survived that is worth a vector by definition.
        jobs.append(("chunk", int(row["id"]), row["text"]))
    for row in messages:
        # Both halves, because the FTS index covers both and the answer is
        # usually the part worth getting back.
        if worth_embedding(row["user"] or "", row["assistant"] or ""):
            jobs.append(("message", int(row["id"]),
                         f"{row['user']}\n{row['assistant']}"))
        else:
            skip("message", int(row["id"]))
    if not jobs:
        # Every row in this pass was skipped. That IS progress — say so, or the
        # caller stops sweeping and the rest of the archive is never reached.
        return len(messages)   # facts and passages are never skipped

    # Halve the batch and try again rather than giving up, because a refusal
    # for being too large and a refusal for having nothing left look identical
    # from here. Without this, one oversized batch stalls the whole archive
    # until somebody notices — with it, a tight budget just means slower
    # progress, which is the correct behaviour and needs no attention.
    global _batch_chars
    size = _batch_chars
    while True:
        room, batch = size, []
        for job in jobs:
            batch.append(job)
            room -= len(job[2])
            if room <= 0:
                break

        vecs = embed([j[2] for j in batch])
        if any(vecs):
            done = 0
            for (kind, ref_id, _), vec in zip(batch, vecs):
                if vec:
                    save(kind, ref_id, vec)
                    done += 1
            # Creep back up on success, so a one-off refusal does not pin the
            # rate down for the rest of the process's life.
            _batch_chars = min(MAX_BATCH_CHARS, int(size * 1.5))
            return done

        if not _blocked_is_quota or size <= MIN_BATCH_CHARS or len(batch) <= 1:
            # Not a size problem, already as small as is worth trying, or the
            # batch is a single row — halving cannot make one passage smaller,
            # so retrying is just spending refusals to learn nothing. The budget
            # is gone for now; the sweep will come back later.
            return 0
        size = max(MIN_BATCH_CHARS, size // 2)
        _batch_chars = size
        log.info("embedding batch too large; trying %d characters", size)


# ---------------------------------------------------------------------------
# Searching
# ---------------------------------------------------------------------------

def search(query: str, limit: int = TOP_K, floor: float = FLOOR,
           kinds: tuple | None = None) -> list[dict]:
    """Rows whose meaning is close to the query. Empty when nothing is close.

    Empty is a perfectly good answer and the common one — a recalled
    irrelevance is noise in the prompt and a lie on the screen.

    `kinds` narrows the search BEFORE ranking, and that is not the same as
    filtering afterwards. Asking for the best five of everything and then
    keeping the passages leaves nothing at all on an archive where messages
    outnumber passages fifty to one — the good passage is real, ranked
    eleventh, and never looked at. Anything hunting one kind must say so here.
    """
    np = _numpy()
    if np is None or not (query or "").strip() or not _ready():
        return []
    with _lock:
        keys = [k for k in _cache.keys() if kinds is None or k[0] in kinds]
        if not keys:
            return []
        matrix = np.stack([_cache[k] for k in keys])

    vec = embed([query], query=True)[0]
    if not vec:
        return []
    q = np.asarray(vec, dtype=np.float32)

    # Both sides are unit vectors, so the dot product IS the cosine. The int8
    # round trip costs about a thousandth, which cannot reorder a shortlist.
    sims = matrix @ q
    order = np.argsort(-sims)[:max(limit * 3, limit)]
    out = []
    for i in order:
        score = float(sims[int(i)])
        if score < floor:
            break                     # sorted, so everything after is worse
        kind, ref_id = keys[int(i)]
        out.append({"kind": kind, "id": ref_id, "similarity": round(score, 4)})
        if len(out) >= limit:
            break
    return out


def forget(kind: str, ref_id: int) -> None:
    """Drop a vector whose row has gone, so it cannot be recalled from limbo."""
    conn = store.connect()
    with _lock:
        _cache.pop((kind, int(ref_id)), None)
    if conn is None:
        return
    try:
        conn.execute("DELETE FROM vectors WHERE kind = ? AND ref_id = ?",
                     (kind, int(ref_id)))
        conn.commit()
    except Exception:  # noqa: BLE001
        pass
