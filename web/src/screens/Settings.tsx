/* Everything technical, in one place you have to ask for.
 *
 * The main screen is a conversation. Which brain answered, how many exchanges
 * are stored, which PC is connected, what the free tier is — all real, all
 * useful once a month, and all noise on a screen you look at twenty times a day.
 * So it lives here.
 */
import { useEffect, useState } from "react";

import { forgetFact, me } from "../lib/api";
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

export function Settings({ token, onClose, onSignOut }: {
  token: string;
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
  }, [token]);

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

        <section className="panel bracket">
          <span className="label">Memory</span>
          <h3>{info?.remembered ?? "—"} exchanges</h3>
          <p className="muted small">
            Kept forever. Jarvis searches all of it, not just recent messages.
          </p>

          <span className="label" style={{ marginTop: "var(--s3)", display: "block" }}>
            Things it remembers about you
          </span>
          {info?.facts?.length ? (
            <ul className="facts">
              {info.facts.map((fact) => (
                <li key={fact}>
                  <span>{fact}</span>
                  <button
                    className="linkish label"
                    disabled={busy}
                    onClick={() => forget(fact.slice(0, 40))}
                    aria-label={`Forget: ${fact}`}
                  >
                    Forget
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted small">
              Nothing yet. Say &ldquo;remember that…&rdquo; and it will keep it for good.
            </p>
          )}
        </section>

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

        <section className="panel bracket">
          <span className="label">Devices</span>
          <ul className="facts">
            {info?.devices?.filter((d) => !d.revoked).map((d) => (
              <li key={d.id}>
                <span>
                  {d.name}
                  {d.id === info.device.id && <span className="muted small"> · this one</span>}
                </span>
                <span className="muted small">{when(d.last_seen)}</span>
              </li>
            ))}
          </ul>
        </section>

        <button className="danger" onClick={onSignOut}>Sign out of this device</button>

        <p className="muted small centre">Jarvis · VONDO v2</p>
      </div>
    </div>
  );
}
