/* What is signed in, and the ability to sign it out.
 *
 * The list was here already; the buttons were not. Every re-added PWA, every
 * browser you sign in from once, every reinstall leaves a row — and behind each
 * row a long-lived token that stays valid for ever. So the list grew, and the
 * only way to invalidate anything was a database.
 *
 * **Adding Revoke made the names a problem.** Every device registered as
 * literally "phone" or "desktop", which was fine while this was read-only and
 * became dangerous the moment there was a button: three rows called "phone" and
 * no way to know which one you are about to sign out of. So new sign-ins carry
 * the browser and platform, every row shows the day it signed in, and any of
 * them can be renamed. The date is the part that always works — two devices can
 * share a name, but they cannot share the moment they arrived.
 *
 * **Revoking asks twice, in place.** It is not destructive — nothing is lost
 * and the device signs in again with the PIN — but it CAN lock a phone out
 * while you are holding it, and one mis-tap doing that is worse than one extra
 * tap every time. Two taps on the same button, no dialog to dismiss.
 *
 * **You cannot revoke the one you are holding.** That is what Sign out is for
 * at the bottom of this screen, and it does the tidying up this cannot.
 */
import { useState } from "react";

import { nameDevice, revokeDevice } from "../lib/api";
import type { Me } from "../lib/types";

/* Taken from the Me type rather than restated, so the two cannot drift. Note
 * `revoked` is a NUMBER: it comes straight out of SQLite, which has no boolean,
 * and writing `revoked?: boolean` here compiled fine until a real response
 * arrived. */
type Device = Me["devices"][number];

function ago(ts?: number | null): string {
  if (!ts) return "—";
  const mins = Math.floor((Date.now() - ts * 1000) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function day(ts?: number | null): string {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleDateString([], {
    day: "numeric", month: "short",
  });
}

export function Devices({ token, devices, thisOne, onChange }: {
  token: string;
  devices: Device[];
  thisOne: string;
  onChange: () => void;
}) {
  const [asking, setAsking] = useState("");
  const [busy, setBusy] = useState("");
  const [editing, setEditing] = useState("");
  const [draft, setDraft] = useState("");

  const live = devices.filter((d) => !d.revoked);

  async function save(id: string) {
    const name = draft.trim();
    setEditing("");
    if (!name) return;
    setBusy(id);
    try {
      await nameDevice(token, id, name);
      onChange();
    } catch {
      /* it keeps the old name; trying again is the whole remedy */
    }
    setBusy("");
  }

  return (
    <section className="panel bracket">
      <span className="label">Devices</span>
      <ul className="facts devices">
        {live.map((d) => {
          const mine = d.id === thisOne;
          return (
            <li key={d.id}>
              {editing === d.id ? (
                <input
                  className="device-name-edit"
                  value={draft}
                  autoFocus
                  maxLength={40}
                  onChange={(e) => setDraft(e.target.value)}
                  onBlur={() => save(d.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") save(d.id);
                    if (e.key === "Escape") setEditing("");
                  }}
                  aria-label={`Rename ${d.name}`}
                />
              ) : (
                <button
                  className="device-name"
                  onClick={() => {
                    setDraft(d.name);
                    setEditing(d.id);
                  }}
                  title="Rename"
                >
                  {d.name}
                  {mine && <span className="muted small"> · this one</span>}
                  {d.kind === "agent" && <span className="muted small"> · PC</span>}
                </button>
              )}

              <span className="device-right">
                {/* Two dates, because they answer different questions: which
                    of these identical-looking rows is which (added), and is
                    this one still in use (seen). */}
                <span className="muted small">
                  {day(d.paired_ts) && `added ${day(d.paired_ts)} · `}
                  {ago(d.last_seen)}
                </span>
                {!mine && (
                  <button
                    className={`linkish label${asking === d.id ? " device-sure" : ""}`}
                    disabled={busy === d.id}
                    onClick={async () => {
                      if (asking !== d.id) {
                        setAsking(d.id);
                        return;
                      }
                      setBusy(d.id);
                      try {
                        await revokeDevice(token, d.id);
                        onChange();
                      } catch {
                        /* it stays listed; trying again is the whole remedy */
                      }
                      setAsking("");
                      setBusy("");
                    }}
                    aria-label={asking === d.id
                      ? `Confirm signing out ${d.name}`
                      : `Sign out ${d.name}`}
                  >
                    {busy === d.id ? "…" : asking === d.id ? "Sure?" : "Revoke"}
                  </button>
                )}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="muted small">
        Tap a name to change it. Revoking makes that device&rsquo;s token
        useless straight away &mdash; it can sign in again with your PIN, and
        nothing is lost.
      </p>
    </section>
  );
}
