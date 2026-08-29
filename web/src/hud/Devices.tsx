/* What is signed in, and the ability to sign it out.
 *
 * The list was here already; the button was not. Every re-added PWA, every
 * browser you sign in from once, every reinstall leaves a row — and behind each
 * row is a long-lived token that stays valid for ever. So the list grew, and
 * the only way to invalidate anything was a database.
 *
 * **Revoking asks twice, in place.** It is not destructive — nothing is lost,
 * and the device signs in again with the PIN — but it CAN lock a phone out
 * while you are holding it, and a single mis-tap doing that is worse than an
 * extra tap every time. Two taps on the same button, no dialog to dismiss.
 *
 * **You cannot revoke the one you are holding.** That is what Sign out is for
 * at the bottom of this screen, and it does the tidying up this cannot.
 */
import { useState } from "react";

import { revokeDevice } from "../lib/api";
import type { Me } from "../lib/types";

/* Taken from the Me type rather than restated, so the two cannot drift. Note
 * `revoked` is a NUMBER: it comes straight out of SQLite, which has no boolean,
 * and writing `revoked?: boolean` here compiled fine until a real response
 * arrived. */
type Device = Me["devices"][number];

function when(ts?: number | null): string {
  if (!ts) return "—";
  const mins = Math.floor((Date.now() - ts * 1000) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function Devices({ token, devices, thisOne, onChange }: {
  token: string;
  devices: Device[];
  thisOne: string;
  onChange: () => void;
}) {
  const [asking, setAsking] = useState("");
  const [busy, setBusy] = useState("");

  const live = devices.filter((d) => !d.revoked);

  return (
    <section className="panel bracket">
      <span className="label">Devices</span>
      <ul className="facts">
        {live.map((d) => {
          const mine = d.id === thisOne;
          return (
            <li key={d.id}>
              <span>
                {d.name}
                {mine && <span className="muted small"> · this one</span>}
                {d.kind === "agent" && <span className="muted small"> · PC</span>}
              </span>
              <span className="device-right">
                <span className="muted small">{when(d.last_seen)}</span>
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
        Revoking makes that device&rsquo;s token useless straight away. It can
        sign in again with your PIN &mdash; nothing is lost.
      </p>
    </section>
  );
}
