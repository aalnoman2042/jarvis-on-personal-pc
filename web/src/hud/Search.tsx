/* One box over everything Jarvis knows.
 *
 * The full-text index was wired for the MODEL long before it was wired for
 * Rohan: Jarvis could search his history and he could not. This is the other
 * half — the conversation, the remembered facts, the diary, the to-do list, the
 * people and what Jarvis has actually done, in one ranked list.
 *
 * Every result says which store it came from, because "where do I know this
 * from?" is most of what you are asking when you search your own life. A hit
 * that is a remembered fact means something quite different from a passing
 * remark in a conversation, and a list that hides the difference is harder to
 * read than one that shows it.
 *
 * Costs nothing to run: SQL and string comparison, no model involved.
 */
import { useEffect, useRef, useState } from "react";

import { searchAll } from "../lib/api";

type Hit = {
  kind: string;
  id: number;
  when: number;
  title: string;
  body: string;
  score: number;
};

const LABEL: Record<string, string> = {
  message: "SAID",
  fact: "REMEMBERED",
  diary: "DIARY",
  task: "TO DO",
  person: "PERSON",
  action: "DID",
};

function when(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (days < 0) return d.toLocaleDateString([], { day: "numeric", month: "short" });
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString([], { day: "numeric", month: "short", year: "2-digit" });
}

export function Search({ token, onClose }: { token: string; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLInputElement>(null);
  const seq = useRef(0);

  useEffect(() => {
    box.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const text = q.trim();
    if (text.length < 2) {
      setHits(null);
      return;
    }
    // Debounced, and every request carries a sequence number. Typing quickly
    // puts several in flight at once, and without this the slowest one wins —
    // so you finish typing and are shown results for a prefix of what you
    // asked, which reads as the search being wrong rather than late.
    const mine = seq.current + 1;
    seq.current = mine;
    setBusy(true);
    const timer = window.setTimeout(async () => {
      try {
        const data = await searchAll(token, text);
        if (mine === seq.current) setHits(data.results);
      } catch {
        if (mine === seq.current) setHits([]);
      }
      if (mine === seq.current) setBusy(false);
    }, 220);
    return () => window.clearTimeout(timer);
  }, [q, token]);

  return (
    <div className="sheet search-sheet">
      <header className="sheet-top">
        <span className="label">Search everything</span>
        <button className="linkish label" onClick={onClose}>Close</button>
      </header>

      <div className="search-box bracket">
        <input
          ref={box}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="A word from anywhere — NILM, dad, exam…"
          aria-label="Search everything Jarvis knows"
        />
      </div>

      <div className="sheet-body">
        {q.trim().length < 2 && (
          <p className="muted small">
            Your conversation, the things Jarvis remembers, the diary, your
            to-do list, the people you know, and what it has done. All of it at
            once — and searching costs nothing.
          </p>
        )}

        {hits && hits.length === 0 && !busy && (
          <p className="muted small">Nothing matches that.</p>
        )}

        {hits && hits.length > 0 && (
          <ul className="hits">
            {hits.map((h, i) => (
              <li key={`${h.kind}-${h.id}-${i}`}>
                <span className={`chip chip-quiet hit-kind hit-${h.kind}`}>
                  {LABEL[h.kind] || h.kind}
                </span>
                <span className="hit-title">{h.title}</span>
                {h.body && <span className="hit-body">{h.body}</span>}
                <span className="hit-when mono">{when(h.when)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
