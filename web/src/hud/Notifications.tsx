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

import {
  askPermission, enablePush, fixExact, pushState, state, test, testPush,
  type NotifyState,
} from "../lib/notify";

export function Notifications({ token }: { token: string }) {
  const [info, setInfo] = useState<NotifyState | null>(null);
  const [web, setWeb] = useState<{
    supported: boolean; subscribed: boolean; available: boolean; subscribers: number;
  } | null>(null);
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setInfo(await state());
    if (!info?.native) setWeb(await pushState(token));
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

      {/* Each link named separately. They all fail as silence, so the only way
          to tell them apart is to report them one at a time. */}
      <div className="chip-row">
        <span className={`chip ${info.permission === "granted" ? "chip-good" : "chip-warn"}`}>
          PERMISSION {info.permission === "granted" ? "OK" : info.permission.toUpperCase()}
        </span>
        {info.channel !== null && (
          <span className={`chip ${info.channel ? "chip-good" : "chip-warn"}`}>
            CHANNEL {info.channel ? "OK" : "MISSING"}
          </span>
        )}
        {info.exact !== null && (
          <span className={`chip ${info.exact ? "chip-good" : "chip-warn"}`}>
            EXACT {info.exact ? "OK" : "OFF"}
          </span>
        )}
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

      {/* The web app has no alarms of its own — no process, no way to wake
          itself — so push is the ONLY thing that reaches it when closed. It is
          therefore the whole feature here, not an extra. */}
      {web && !info.native && (
        <>
          <div className="chip-row">
            <span className={`chip ${web.subscribed ? "chip-good" : "chip-warn"}`}>
              {web.subscribed ? "PUSH ON" : "PUSH OFF"}
            </span>
            {web.subscribers > 0 && (
              <span className="chip chip-quiet">{web.subscribers} DEVICE
                {web.subscribers === 1 ? "" : "S"}</span>
            )}
          </div>
          <p className="muted small">
            {web.subscribed
              ? "Reminders arrive even with Jarvis closed — the browser wakes for them."
              : web.supported
                ? "Turn this on and reminders arrive with Jarvis closed. Without it they can only appear while this tab is open."
                : "This browser cannot receive push. Chrome or Edge on Android can."}
          </p>
          <div className="chip-row">
            {web.supported && !web.subscribed && (
              <button
                className="chip chip-hot"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setSaid(await enablePush(token));
                  await refresh();
                  setBusy(false);
                }}
              >
                TURN ON
              </button>
            )}
            {web.subscribed && (
              <button
                className="chip chip-quiet"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setSaid(await testPush(token));
                  setBusy(false);
                }}
              >
                TEST FROM SERVER
              </button>
            )}
          </div>
        </>
      )}

      {said && <p className="muted small notify-said">{said}</p>}

      {/* Said plainly because it is the thing people assume is untrue. A
          reminder waiting costs nothing at all: the phone's own alarm clock
          holds it, exactly as it holds yours. Jarvis is not running, not
          polling, and holds no connection while it waits. */}
      {info.native && (
        <p className="muted small">
          Waiting costs no battery — the phone holds these the same way it holds
          an alarm. Jarvis is not running in the background, and needs no
          battery-optimisation exemption.
        </p>
      )}

      {info.permission === "denied" && (
        <p className="muted small">
          Android will not ask twice. Turn it back on in Settings → Apps → Jarvis
          → Notifications, then press Recheck.
        </p>
      )}
    </section>
  );
}
