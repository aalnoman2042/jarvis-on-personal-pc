/* Everything technical, in one place you have to ask for.
 *
 * The main screen is a conversation. Which brain answered, how many exchanges
 * are stored, which PC is connected, what the free tier is — all real, all
 * useful once a month, and all noise on a screen you look at twenty times a day.
 * So it lives here.
 */
import { useEffect, useState } from "react";

import { Backup } from "../hud/Backup";
import { Notifications } from "../hud/Notifications";
import { VoicePicker } from "../hud/VoicePicker";
import { Devices } from "../hud/Devices";
import { Corrections } from "../hud/Corrections";
import { Remembered } from "../hud/Remembered";
import { forgetCorrection, forgetFact, me } from "../lib/api";
import type { Me } from "../lib/types";

function when(ts?: number | null): string {
  if (!ts) return "—";
  const mins = Math.floor((Date.now() - ts * 1000) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

const BRAIN_NOTES: Record<string, string> = {
  groq: "Groq · free tier · fastest",
  gemini: "Gemini · free tier · backup",
  free: "Offline rules · no AI · last resort",
  ollama: "Local model · not installed",
  claude: "Claude · paid",
};

function brainLine(name: string): { title: string; note: string } {
  // The chain is named like "groq+free": whoever leads is what is answering.
  const lead = (name || "").split("+")[0];
  return { title: lead || "unknown", note: BRAIN_NOTES[lead] || "" };
}

export function Settings({ token, refresh, onClose, onSignOut }: {
  token: string;
  refresh?: number;
  onClose: () => void;
  onSignOut: () => void;
}) {
  const [info, setInfo] = useState<Me | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setInfo(await me(token));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load settings.");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, refresh]);

  async function forget(fragment: string) {
    setBusy(true);
    try {
      const result = await forgetFact(token, fragment);
      setInfo((prev) => (prev ? { ...prev, facts: result.facts } : prev));
    } catch {
      setError("Couldn't change that just now.");
    }
    setBusy(false);
  }

  const brain = brainLine(info?.brain || "");
  const pc = info?.pc?.[0];

  return (
    <div className="sheet">
      <header className="sheet-top">
        <span className="label">Settings</span>
        <button className="linkish label" onClick={onClose}>Close</button>
      </header>

      <div className="sheet-body">
        {error && <p className="pin-msg pin-msg-bad">{error}</p>}

        <section className="panel bracket">
          <span className="label">Brain</span>
          <h3>{brain.title}</h3>
          <p className="muted">{brain.note}</p>
          <p className="muted small">
            If the free tier runs out or the service is down, Jarvis drops to the
            next brain on its own and keeps answering.
          </p>
        </section>

        {/* A count and a list are different kinds of thing and no longer share
            a panel: the count is one line for ever, the list grows to a dozen
            entries and was pushing everything below it off a phone screen. */}
        <section className="panel bracket">
          <span className="label">Memory</span>
          <h3>{info?.remembered ?? "—"} exchanges</h3>
          <p className="muted small">
            Kept forever. Jarvis searches all of it, not just recent messages.
          </p>
        </section>

        <Remembered
          facts={info?.facts ?? []}
          busy={busy}
          onForget={(fragment) => forget(fragment)}
        />

        <Corrections
          items={info?.corrections ?? []}
          busy={busy}
          onForget={async (id) => {
            setBusy(true);
            try {
              await forgetCorrection(token, id);
              await load();
            } catch {
              setError("Couldn't unlearn that just now.");
            }
            setBusy(false);
          }}
        />

        <Notifications token={token} />

        <VoicePicker />

        <section className="panel bracket">
          <span className="label">Your PC</span>
          <h3>{pc ? pc.name : "Not connected"}</h3>
          {pc ? (
            <p className="muted small mono">
              CPU {pc.telemetry?.cpu ?? "—"}% · Memory {pc.telemetry?.memory ?? "—"}%
              {typeof pc.telemetry?.battery === "number" ? ` · Battery ${pc.telemetry.battery}%` : ""}
              <br />
              last heard {when(pc.last_seen)}
            </p>
          ) : (
            <p className="muted small">
              Run <span className="mono">start_agent.bat</span> on your PC to open
              apps and see its CPU from here. Everything else works without it.
            </p>
          )}
        </section>

        {info?.recent_actions?.length ? (
          <section className="panel bracket">
            <span className="label">Recently done</span>
            <ul className="acts">
              {info.recent_actions.map((a, i) => (
                <li key={i}>
                  <span className="mono act-tool">{a.tool.replace(/_/g, " ")}</span>
                  <span className="muted small">{a.args || ""}</span>
                  <span className="muted small">{when(a.ts)}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {info?.people?.length ? (
          <section className="panel bracket">
            <span className="label">People</span>
            <p className="muted small">
              Say &ldquo;call dad&rdquo; and Jarvis looks the number up rather
              than guessing it. Numbers stay on the server and are never sent to
              this screen.
            </p>
            <ul className="facts">
              {info.people.map((p) => (
                <li key={p.name}>
                  <span>{p.name}</span>
                  <span className="muted small">
                    {[p.phone && "phone", p.email && "email"].filter(Boolean).join(" · ") || "—"}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <Devices
          token={token}
          devices={info?.devices ?? []}
          thisOne={info?.device?.id ?? ""}
          onChange={load}
        />

        <Backup token={token} />

        <button className="danger" onClick={onSignOut}>Sign out of this device</button>

        <p className="muted small centre">Jarvis · VONDO v2</p>
      </div>
    </div>
  );
}
