/* The HUD.
 *
 * Layout is two columns on a desktop — the reactor and conversation in the
 * middle, telemetry down the side — and a single reactor-first column on a
 * phone. Same build, same components; only the grid changes.
 */
import { useState } from "react";

import { Composer } from "./hud/Composer";
import { Log } from "./hud/Log";
import { Reactor } from "./hud/Reactor";
import { Telemetry } from "./hud/Telemetry";
import { useInstall } from "./lib/install";
import { useVondo } from "./lib/socket";
import { clearToken, readToken, writeToken } from "./lib/store";
import { Pin } from "./screens/Pin";

const CONN_TEXT: Record<string, string> = {
  connecting: "Connecting",
  online: "Online",
  offline: "Reconnecting",
  unauthorised: "Not authorised",
};

function Hud({ token, onForget }: { token: string; onForget: () => void }) {
  const jarvis = useVondo(token);
  const { canInstall, install } = useInstall();
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
        <span className="label brain">{jarvis.brain || "—"}</span>
        <button className="linkish label" onClick={onForget}>
          Sign out
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
    </div>
  );
}

export default function App() {
  const [token, setToken] = useState(readToken);

  function paired(next: string) {
    writeToken(next);
    setToken(next);
  }

  function forget() {
    clearToken();
    setToken("");
  }

  if (!token) return <Pin onIn={paired} />;
  // Keyed on the token so unpairing and pairing again builds a fresh socket
  // rather than reusing one wired to a token that no longer works.
  return <Hud key={token} token={token} onForget={forget} />;
}
