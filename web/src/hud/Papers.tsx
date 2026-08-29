/* The papers, notes and drafts Jarvis can read.
 *
 * Everything else it knows came out of a conversation. This is the shelf: hand
 * it a PDF or a note and it can answer from what is inside, by meaning rather
 * than by filename — "what did that paper say about coarse metering" works
 * without those words appearing anywhere in it.
 *
 * **The waiting state is shown, not hidden.** Embedding happens in the sweep,
 * not on upload, so for a moment after filing a document is stored and not yet
 * findable. Drawing it as ready would make the first search look broken, which
 * is the fastest way to stop trusting a search. And when indexing is blocked —
 * a used-up free tier, most often — it says so in words, because a backlog with
 * no explanation reads as a fault and this one fixes itself.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { documents, fileDocument, forgetDocument } from "../lib/api";

type Doc = {
  id: number;
  name: string;
  kind: string;
  added: number;
  pages: number;
  bytes: number;
  note: string;
  passages: number;
};

function size(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${bytes}B`;
}

export function Papers({ token }: { token: string }) {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [pending, setPending] = useState(0);
  const [blocked, setBlocked] = useState("");
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");
  const picker = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await documents(token);
      setDocs(data.documents);
      setPending(data.pending);
      setBlocked(data.blocked || "");
    } catch {
      /* a shelf that cannot load is not worth an error on the board */
    }
  }, [token]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function take(file: File | undefined) {
    if (!file) return;
    setProblem("");
    setBusy(file.name);
    try {
      const result = await fileDocument(token, file);
      await refresh();
      setProblem(result.why || "");
    } catch (err) {
      // The interesting failure is a scan — pictures of a page rather than a
      // page — and the server says so in words. Showing them beats "400".
      setProblem(err instanceof Error ? err.message : "That didn't work.");
    }
    setBusy("");
    if (picker.current) picker.current.value = "";
  }

  return (
    <section className="panel bracket panel-wide papers">
      <div className="brief-top">
        <span className="label">Papers &amp; notes</span>
        <button
          className="linkish label"
          onClick={() => picker.current?.click()}
          disabled={Boolean(busy)}
        >
          {busy ? "Reading…" : "Add"}
        </button>
      </div>

      <input
        ref={picker}
        type="file"
        accept=".pdf,.txt,.md,.markdown,.csv,.json,.py,.js,.ts,.html"
        hidden
        onChange={(e) => take(e.target.files?.[0])}
      />

      {docs && docs.length === 0 && !busy && (
        <p className="muted small">
          Nothing filed yet. Add a paper or a note and I can answer from what is
          inside it &mdash; by what it says, not what it is called.
        </p>
      )}

      {docs && docs.length > 0 && (
        <ul className="papers-list">
          {docs.map((d) => (
            <li key={d.id}>
              <span className="paper-name">{d.name}</span>
              <span className="paper-meta mono">
                {d.passages} passages
                {d.pages ? ` · ${d.pages}pp` : ""} · {size(d.bytes)}
              </span>
              {d.note && <span className="paper-note">{d.note}</span>}
              <button
                className="linkish label paper-drop"
                onClick={async () => {
                  await forgetDocument(token, d.id);
                  refresh();
                }}
                aria-label={`Forget ${d.name}`}
              >
                Forget
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* Two different states, and conflating them would be the mistake: still
          working through the backlog, versus stopped and waiting on something.
          Only the second needs anything from anybody, and neither is a fault. */}
      {pending > 0 && !blocked && (
        <p className="muted small">
          Reading {pending} more passage{pending === 1 ? "" : "s"} in the
          background. Searching works on everything already read.
        </p>
      )}
      {blocked && <p className="muted small papers-blocked">{blocked}</p>}
      {problem && <p className="muted small">{problem}</p>}
    </section>
  );
}
