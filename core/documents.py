"""Papers, notes and anything else worth being able to find again.

Everything Jarvis knew came from conversations. The actual work — the papers,
the drafts, the notes — lived in folders it could not see, so "find the paper I
was reading about low sampling rate NILM" had no answer, and the one thing a
research assistant ought to be good at was the one thing it could not do.

A document goes in, comes out as text, is cut into pieces, and each piece gets
an embedding from `core/memory/vectors.py`. Retrieval is then the same machinery
as everything else: cosine over a shortlist, one measured floor, no new ideas.

**Chunks, not whole documents, and that is the whole trick.** One vector for a
forty-page paper is a vector for nothing in particular — the average of the
abstract, the methodology and the references, close to every query and useful
for none. A paragraph has one subject, so its vector points somewhere.

**A page number is not a chunk.** PDF text extraction returns running heads,
footers, page numbers and stray column fragments, and every one of them becomes
an indexed line that matches nothing and pollutes the results. Lines that carry
no sentence are dropped before anything is embedded.

**A scanned PDF must say so.** It is a stack of photographs with no text layer,
and extracting it yields nothing at all. Storing an empty document and reporting
success is the worst outcome: the paper looks filed and is not there, so the
first time you search for it you conclude the search is broken. `read` returns
what it got and how many characters that was, and the caller refuses the empty
ones out loud.

Nothing here raises into a conversation.
"""
from __future__ import annotations

import hashlib
import logging
import re

from core import clock
from core.memory import store

log = logging.getLogger("vondo.documents")

# Roughly a paragraph. Small enough that a chunk is about one thing, large
# enough to carry the sentence around the fact — a chunk of one line embeds
# almost as poorly as a chunk of one book.
TARGET = 900
# Carried from the end of one chunk into the start of the next, so a sentence
# split across a boundary is still whole somewhere.
OVERLAP = 140
MIN_CHUNK = 120

MAX_BYTES = 20 * 1024 * 1024
MAX_CHARS = 2_000_000        # ~600 pages; past this it is not a document

TEXT_KINDS = {"txt", "md", "markdown", "csv", "json", "py", "js", "ts", "html"}


def kind_of(name: str) -> str:
    ext = (name or "").rsplit(".", 1)[-1].lower() if "." in (name or "") else ""
    if ext == "pdf":
        return "pdf"
    return ext if ext in TEXT_KINDS else ""


# ---------------------------------------------------------------------------
# Getting the words out
# ---------------------------------------------------------------------------

def _tidy(line: str) -> str:
    # Ligatures survive extraction and break every search for the word they are
    # inside: "identiﬁcation" is not "identification" to any matcher.
    for bad, good in (("ﬀ", "ff"), ("ﬁ", "fi"), ("ﬂ", "fl"),
                      ("ﬃ", "ffi"), ("ﬄ", "ffl"),
                      ("’", "'"), ("‘", "'"),
                      ("“", '"'), ("”", '"'),
                      ("–", "-"), ("—", "-")):
        line = line.replace(bad, good)
    return " ".join(line.split())


def _worth_keeping(line: str) -> bool:
    """Is this a sentence, or is it furniture?

    Running heads, page numbers, column fragments and reference numbering all
    come out of a PDF looking like text. Indexed, they match nothing and dilute
    the chunk they sit in.
    """
    if len(line) < 3:
        return False
    letters = sum(1 for c in line if c.isalpha())
    if letters < 3:
        return False           # "12", "3.1", "|", "· · ·"
    # Mostly digits and punctuation: a page number, a table rule, a citation
    # block. A real sentence is mostly letters.
    return letters / len(line) > 0.5


def read(data: bytes, name: str) -> tuple[str, int]:
    """The text of a document, and how many pages it had (0 for plain text).

    Returns ("", 0) when nothing could be read — which is a real answer, not an
    error. The commonest cause is a scanned PDF: a stack of photographs with no
    text layer, from which there is genuinely nothing to extract.
    """
    kind = kind_of(name)
    if not kind:
        return ("", 0)
    if kind != "pdf":
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return (data.decode(encoding), 0)
            except Exception:  # noqa: BLE001
                continue
        return ("", 0)

    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001  (one bad page must not lose the rest)
                pages.append("")
            if sum(len(p) for p in pages) > MAX_CHARS:
                break
        return ("\n\n".join(pages), len(reader.pages))
    except Exception as exc:  # noqa: BLE001
        log.info("could not read %s: %s", name, str(exc)[:120])
        return ("", 0)


def clean(text: str) -> str:
    """Extracted text with the furniture taken out, paragraphs intact.

    The blank lines have to survive. `chunks` splits on them, and dropping them
    along with the page numbers — which is what happens if every line is simply
    tested and discarded — leaves one unbroken wall of text, so a forty-page
    paper becomes a single chunk and the whole point is lost.
    """
    out: list[str] = []
    for line in (text or "").splitlines():
        tidied = _tidy(line)
        if not tidied:
            # A paragraph break. Never two in a row: extraction is full of them
            # and they would split a paragraph that was merely double-spaced.
            if out and out[-1] != "":
                out.append("")
        elif _worth_keeping(tidied):
            out.append(tidied)
        elif out and out[-1] != "":
            # Furniture sits BETWEEN things — a running head at a page break,
            # a page number under the last line. Removing it silently would
            # glue the end of one page to the start of the next.
            out.append("")
    return "\n".join(out).strip()


# ---------------------------------------------------------------------------
# Cutting it up
# ---------------------------------------------------------------------------

def chunks(text: str) -> list[str]:
    """Pieces of about a paragraph each, with a little carried between them.

    Paragraph boundaries first, sentence boundaries when a paragraph is too
    long, and only then a hard cut. Splitting at a fixed character count is
    easier and produces chunks that begin mid-clause, which embed as badly as
    they read.
    """
    body = (text or "").strip()
    if not body:
        return []

    pieces: list[str] = []
    for para in re.split(r"\n\s*\n", body):
        para = " ".join(para.split())
        if not para:
            continue
        if len(para) <= TARGET:
            pieces.append(para)
            continue
        # Too long: break on sentence ends, and accumulate back up to TARGET so
        # a paper written in short sentences does not become a chunk each.
        held = ""
        for sentence in re.split(r"(?<=[.!?])\s+", para):
            if len(held) + len(sentence) + 1 <= TARGET:
                held = f"{held} {sentence}".strip()
                continue
            if held:
                pieces.append(held)
            # A single sentence longer than a chunk is a table or a formula.
            while len(sentence) > TARGET:
                pieces.append(sentence[:TARGET])
                sentence = sentence[TARGET - OVERLAP:]
            held = sentence
        if held:
            pieces.append(held)

    # Merge the runts. A heading on its own is not worth a vector, but a heading
    # in front of the paragraph it introduces makes that paragraph easier to
    # find, not harder.
    merged: list[str] = []
    for piece in pieces:
        if merged and len(piece) < MIN_CHUNK and len(merged[-1]) + len(piece) < TARGET * 1.4:
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)

    # Carry the tail of each chunk into the next, so a fact sitting across a
    # boundary is whole in at least one of them.
    out: list[str] = []
    for i, piece in enumerate(merged):
        if i and OVERLAP:
            tail = merged[i - 1][-OVERLAP:]
            cut = tail.find(" ")
            piece = (tail[cut + 1:] if cut >= 0 else tail) + " " + piece
        out.append(piece.strip())
    return [p for p in out if len(p) >= 20]


# ---------------------------------------------------------------------------
# Keeping it
# ---------------------------------------------------------------------------

def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:32]


def add(data: bytes, name: str, note: str = "") -> dict:
    """File a document. Returns what happened, in words that can be shown.

    Never raises, and never reports success for a document it could not read —
    a paper that looks filed and is not there is worse than one that visibly
    failed, because the first search for it reads as the search being broken.
    """
    name = " ".join((name or "document").split())[:200]
    if not data:
        return {"ok": False, "why": "That file was empty."}
    if len(data) > MAX_BYTES:
        return {"ok": False, "why": f"That file is too big — {len(data) // 1024 // 1024}MB."}
    if not kind_of(name):
        return {"ok": False,
                "why": f"I can read PDFs and text files. {name} is neither."}

    conn = store.connect()
    if conn is None:
        return {"ok": False, "why": "I can't reach my memory just now."}

    mark = fingerprint(data)
    try:
        seen = conn.execute("SELECT id, name FROM documents WHERE sha = ?",
                            (mark,)).fetchone()
        if seen:
            return {"ok": True, "id": int(seen["id"]), "chunks": 0,
                    "why": f"I already have that one, as {seen['name']}."}
    except Exception:  # noqa: BLE001
        pass

    raw, pages = read(data, name)
    body = clean(raw)
    pieces = chunks(body)
    if not pieces:
        return {"ok": False, "why": (
            f"I couldn't get any text out of {name}. If it's a scan, it is "
            f"pictures of a page rather than a page — there is nothing in it "
            f"to read.")}

    try:
        cursor = conn.execute(
            "INSERT INTO documents(name, kind, sha, added, pages, bytes, note) "
            "VALUES (?,?,?,?,?,?,?)",
            (name, kind_of(name), mark, round(clock.now(), 1), int(pages),
             len(data), " ".join((note or "").split())[:300]))
        doc_id = int(cursor.lastrowid)
        for seq, piece in enumerate(pieces):
            conn.execute(
                "INSERT INTO doc_chunks(doc_id, seq, text) VALUES (?,?,?)",
                (doc_id, seq, piece))
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        log.info("could not store %s: %s", name, str(exc)[:160])
        return {"ok": False, "why": "I couldn't file that just now."}

    return {"ok": True, "id": doc_id, "chunks": len(pieces), "pages": pages,
            "why": f"Filed {name} — {len(pieces)} passages"
                   + (f" from {pages} pages." if pages else ".")}


def all_documents(limit: int = 100) -> list[dict]:
    conn = store.connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT d.*, (SELECT COUNT(*) FROM doc_chunks c WHERE c.doc_id = d.id) "
            "AS passages FROM documents d ORDER BY d.added DESC LIMIT ?",
            (limit,)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [dict(r) for r in rows]


def forget(doc_id: int) -> bool:
    """Remove a document, its passages and their vectors.

    All three, or the vectors outlive the text they came from and a search
    returns a hit that cannot be shown.
    """
    conn = store.connect()
    if conn is None:
        return False
    try:
        ids = [int(r["id"]) for r in conn.execute(
            "SELECT id FROM doc_chunks WHERE doc_id = ?", (int(doc_id),)).fetchall()]
        conn.execute("DELETE FROM doc_chunks WHERE doc_id = ?", (int(doc_id),))
        cursor = conn.execute("DELETE FROM documents WHERE id = ?", (int(doc_id),))
        conn.commit()
    except Exception:  # noqa: BLE001
        return False
    try:
        from core.memory import vectors
        for chunk_id in ids:
            vectors.forget("chunk", chunk_id)
    except Exception:  # noqa: BLE001
        pass
    return bool(cursor.rowcount)


def passage(chunk_id: int) -> dict | None:
    """One passage and the document it came from, for showing a search hit."""
    conn = store.connect()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT c.id, c.text, c.seq, d.id AS doc_id, d.name, d.added "
            "FROM doc_chunks c JOIN documents d ON d.id = c.doc_id "
            "WHERE c.id = ?", (int(chunk_id),)).fetchone()
    except Exception:  # noqa: BLE001
        return None
    return dict(row) if row else None
