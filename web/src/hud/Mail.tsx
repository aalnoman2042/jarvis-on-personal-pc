/* The inboxes, ranked rather than listed.
 *
 * A mail client shows you everything newest-first, which is the one ordering
 * that guarantees the important thing is wherever the unimportant things put
 * it. This shows what is worth your attention, best first, and says WHY each
 * one made the cut — "someone you know", "mentions deadline". A ranking you
 * cannot see the reasoning of is a ranking you end up double-checking, at which
 * point it has saved you nothing.
 *
 * Read-only, and visibly so: there is nothing here to reply, archive or delete
 * with, because the code underneath cannot do any of those things.
 *
 * Nothing is fetched until the panel is opened. Checking mail is a network
 * round-trip to an IMAP server per account, and doing that on every board load
 * would make the whole app feel slow for a thing you glance at twice a day.
 */
import { useState } from "react";

import { mail } from "../lib/api";
import type { MailMessage } from "../lib/types";

function ago(ts: number): string {
  if (!ts) return "";
  const mins = Math.floor((Date.now() - ts * 1000) / 60000);
  if (mins < 60) return `${Math.max(1, mins)}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

export function Mail({ token }: { token: string }) {
  const [items, setItems] = useState<MailMessage[] | null>(null);
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [off, setOff] = useState(false);

  async function load() {
    setBusy(true);
    setError("");
    try {
      const data = await mail(token, 2);
      if (!data.configured) {
        setOff(true);
      } else {
        setItems(data.messages);
        setSaid(data.said);
      }
    } catch {
      setError("Couldn't reach the mailboxes.");
    }
    setBusy(false);
  }

  if (off) {
    return (
      <section className="panel bracket panel-wide">
        <span className="label">Mail</span>
        <p className="muted small">
          No mailboxes connected. Each one needs an app password — see
          SECRETS.local.md for the two-line setup.
        </p>
      </section>
    );
  }

  return (
    <section className="panel bracket panel-wide">
      <div className="vision-top">
        <span className="label">Mail</span>
        <button className="chip chip-quiet" onClick={load} disabled={busy}>
          {busy ? "READING" : items ? "REFRESH" : "CHECK"}
        </button>
      </div>

      {error && <p className="mic-error label">{error}</p>}

      {!items && !busy && !error && (
        <p className="muted small">
          Ranked by who sent it and what it is about — not by what arrived last.
          Nothing is fetched until you ask.
        </p>
      )}

      {said && <p className="mail-said">{said}</p>}

      {items && items.length > 0 && (
        <ul className="mail-list">
          {items.map((m, i) => (
            <li key={i} className={m.score >= 6 ? "mail-hot" : m.score < 2 ? "mail-cold" : ""}>
              <span className="mail-who">{m.from}</span>
              <span className="mail-box chip chip-quiet" title={m.account}>
                {m.account}
              </span>
              <span className="mail-subject">{m.subject}</span>
              <span className="mail-meta mono">
                {m.unread ? "● " : ""}
                {ago(m.date)}
              </span>
              {m.why && <span className="mail-why label">{m.why}</span>}
            </li>
          ))}
        </ul>
      )}

      {items && items.length === 0 && (
        <p className="muted small">Nothing worth your attention right now.</p>
      )}
    </section>
  );
}
