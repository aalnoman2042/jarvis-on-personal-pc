/* Whether a reminder will actually reach you, and a way to prove it.
 *
 * This panel exists because the honest answer to "are notifications working?"
 * used to be "you'll find out when you miss something". Every part of the chain
 * can fail quietly and independently — permission never asked, permission
 * refused, Android withholding exact timing, nothing scheduled because the app
 * has not been opened since the reminder was set — and all of those look
 * identical from the outside: silence.
 *
 * So each one is named, and the test button settles it in eight seconds.
 */
import { useEffect, useState } from "react";

import { askPermission, fixExact, state, test, type NotifyState } from "../lib/notify";

export function Notifications() {
  const [info, setInfo] = useState<NotifyState | null>(null);
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setInfo(await state());
  }

  useEffect(() => {
    refresh();
  }, []);

  async function allow() {
    setBusy(true);
    await askPermission();
    await refresh();
    setBusy(false);
  }

  async function fire() {
    setBusy(true);
    setSaid(await test());
    await refresh();
    setBusy(false);
  }

  if (!info) return null;

  const working = info.permission === "granted" && info.exact !== false;

  return (
    <section className="panel bracket">
      <span className="label">Reminders reaching you</span>

      <h3 className="panel-head">
        {working ? "Working" : info.permission === "granted" ? "Partly" : "Not yet"}
        <span className={`chip panel-badge ${working ? "chip-good" : "chip-warn"}`}>
          {/* "APP · NO ALARMS" is its own state: inside the app, but this build
              predates the alarm plugin. Reminders then appear in the app and
              never in the notification bar, which is exactly the symptom that
              is impossible to diagnose if it is labelled BROWSER. */}
          {!info.native ? "BROWSER" : info.scheduled === 0 && info.exact === null
            ? "APP · NO ALARMS"
            : "APP"}
        </span>
      </h3>

      {info.problem ? (
        <p className="muted small">{info.problem}</p>
      ) : (
        <p className="muted small">
          {info.native
            ? "Alarms are held by the phone, so they arrive with the app closed and no signal."
            : "These arrive while this tab is open."}
        </p>
      )}

      <div className="stat-row">
        <span className="mono">{info.scheduled}</span>
        <span className="muted small">scheduled on this device</span>
      </div>

      <div className="chip-row">
        {info.permission !== "granted" && (
          <button className="chip chip-hot" onClick={allow} disabled={busy}>
            ALLOW
          </button>
        )}
        {info.exact === false && (
          <button className="chip chip-warn" onClick={fixExact} disabled={busy}>
            FIX TIMING
          </button>
        )}
        <button className="chip chip-quiet" onClick={fire} disabled={busy}>
          {busy ? "…" : "SEND A TEST"}
        </button>
        <button className="chip chip-quiet" onClick={refresh} disabled={busy}>
          RECHECK
        </button>
      </div>

      {said && <p className="muted small notify-said">{said}</p>}

      {info.permission === "denied" && (
        <p className="muted small">
          Android will not ask twice. Turn it back on in Settings → Apps → Jarvis
          → Notifications, then press Recheck.
        </p>
      )}
    </section>
  );
}
