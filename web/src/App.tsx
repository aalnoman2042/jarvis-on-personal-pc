/* The HUD.
 *
 * Layout is two columns on a desktop — the reactor and conversation in the
 * middle, telemetry down the side — and a single reactor-first column on a
 * phone. Same build, same components; only the grid changes.
 */
import { useEffect, useState } from "react";

import { Composer } from "./hud/Composer";
import { Log } from "./hud/Log";
import { Reactor } from "./hud/Reactor";
import { Telemetry } from "./hud/Telemetry";
import { useInstall } from "./lib/install";
import { useVondo } from "./lib/socket";
import { clearToken, readToken, writeToken } from "./lib/store";
import { Pin } from "./screens/Pin";
import { Settings } from "./screens/Settings";

const CONN_TEXT: Record<string, string> = {
  connecting: "Connecting",
  online: "Online",
  offline: "Reconnecting",
  unauthorised: "Not authorised",
};

function Hud({ token, onForget }: { token: string; onForget: () => void }) {
  const jarvis = useVondo(token);
  const { canInstall, install } = useInstall();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const busy = jarvis.state === "thinking";

  // A revoked or unknown token cannot fix itself by retrying, so say what
  // happened and offer the one thing that helps.
  if (jarvis.conn === "unauthorised") {
    return (
      <div className="pair">
        <div className="pair-card bracket">
          <span className="label">Refused</span>
          <h1>This device isn&rsquo;t authorised</h1>
          <p className="pair-help">
            Its access was revoked, or the server no longer recognises it. Enter
            your PIN again to carry on.
          </p>
          <button className="pair-go" onClick={onForget}>
            Enter PIN
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="hud">
      <div className="sweep" aria-hidden />
      <header className="topbar">
        <span className="wordmark">VONDO</span>
        <span className={`conn conn-${jarvis.conn}`}>
          <span className="dot" aria-hidden />
          {CONN_TEXT[jarvis.conn] ?? jarvis.conn}
        </span>
        {jarvis.queued > 0 && (
          <span className="held label" title="Waiting for a connection">
            {jarvis.queued} held
          </span>
        )}
        {canInstall && (
          <button className="install install-small" onClick={install} type="button">
            Install
          </button>
        )}
        {/* Which brain answered, how much is stored, which PC is linked — all of
            it lives behind this. The main screen is a conversation, not a
            dashboard. */}
        <button className="gear" onClick={() => setSettingsOpen(true)} aria-label="Settings">
          <span aria-hidden>&#9881;</span>
        </button>
      </header>

      <main className="stage">
        <section className="core">
          <div className="reactor-wrap">
            <Reactor state={jarvis.state} />
            <span className={`reactor-state label state-${jarvis.state}`}>{jarvis.state}</span>
          </div>
          <Log lines={jarvis.log} />
          <Composer onSay={jarvis.say} busy={busy} />
        </section>

        <Telemetry data={jarvis.telemetry} online={jarvis.pcOnline} />
      </main>

      {settingsOpen && (
        <Settings token={token} onClose={() => setSettingsOpen(false)} onSignOut={onForget} />
      )}
    </div>
  );
}

/* The boot sequence. Shown once per launch and then never again in that
   session — a startup animation you sit through every time you switch back to
   the app stops being atmosphere and becomes a delay. */
function Boot() {
  const [gone, setGone] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setGone(true), 2000);
    return () => window.clearTimeout(t);
  }, []);
  if (gone) return null;
  return (
    <div className="boot" aria-hidden>
      <span>&gt; core online</span>
      <span>&gt; memory linked</span>
      <span>&gt; uplink established</span>
      <span>&gt; jarvis ready</span>
    </div>
  );
}

export default function App() {
  const [token, setToken] = useState(readToken);
  const [booted, setBooted] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => setBooted(true), 2100);
    return () => window.clearTimeout(t);
  }, []);

  function paired(next: string) {
    writeToken(next);
    setToken(next);
  }

  function forget() {
    clearToken();
    setToken("");
  }

  if (!booted) return <Boot />;
  if (!token) return <Pin onIn={paired} />;
  // Keyed on the token so unpairing and pairing again builds a fresh socket
  // rather than reusing one wired to a token that no longer works.
  return <Hud key={token} token={token} onForget={forget} />;
}
