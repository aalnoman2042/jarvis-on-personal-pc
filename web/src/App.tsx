/* The HUD.
 *
 * Home is the board — what is coming up, what the PC is doing, what Jarvis
 * remembers. The conversation is a drawer over it, opened from the button in
 * the corner, and settings is a second drawer behind the gear. One socket
 * underneath all three, held by this component, so opening and closing a drawer
 * never drops the connection or loses the log.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { ChatSheet } from "./hud/ChatSheet";
import { Search } from "./hud/Search";
import { Whisper } from "./hud/Whisper";
import { useInstall } from "./lib/install";
import { useVondo } from "./lib/socket";
import * as speech from "./lib/speak";
import { useVoice } from "./lib/voice";
import { clearToken, readToken, writeToken } from "./lib/store";
import { Dashboard } from "./screens/Dashboard";
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
  const [open, setOpen] = useState<"none" | "chat" | "settings" | "search">("none");
  const [talkback, setTalkback] = useState(speech.enabled);

  // Something said out loud goes straight to Jarvis. Held in a ref because the
  // recorder's callback is built once and would otherwise keep the first
  // render's `say` for ever.
  const say = useRef(jarvis.say);
  say.current = jarvis.say;
  // Whether the last thing said was spoken rather than typed. If you talked to
  // it, it talks back — the mute toggle is about unsolicited noise, not about
  // being ignored when you asked out loud with the screen at arm's length.
  const spokeToIt = useRef(false);
  const heard = useCallback((text: string) => {
    spokeToIt.current = true;
    say.current(text);
  }, []);
  const voice = useVoice(token, heard);

  // Read the newest reply aloud, once. Counting replies rather than watching the
  // array means a re-render for any other reason cannot make it repeat itself.
  const spokenTo = useRef(0);
  useEffect(() => {
    const replies = jarvis.log.filter((line) => line.who === "jarvis");
    if (replies.length <= spokenTo.current) {
      spokenTo.current = replies.length; // the log was cleared or trimmed
      return;
    }
    spokenTo.current = replies.length;
    if (talkback || spokeToIt.current) {
      speech.speak(replies[replies.length - 1].text);
    }
    spokeToIt.current = false;
  }, [jarvis.log, talkback]);

  // Talking over yourself is the one thing a voice interface must never do.
  useEffect(() => {
    if (voice.listening) speech.silence();
  }, [voice.listening]);

  function toggleTalkback() {
    const next = !talkback;
    speech.setEnabled(next);
    setTalkback(next);
  }

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
        {/* Muting is one tap and it is remembered. Jarvis reading answers aloud
            is the point on a phone and an ambush in a quiet room. */}
        <button className="gear" onClick={() => setOpen("search")}
                aria-label="Search everything">
          <span aria-hidden>&#8981;</span>
        </button>
        {speech.available() && (
          <button
            className={`gear speaker${talkback ? "" : " speaker-off"}`}
            onClick={toggleTalkback}
            aria-pressed={talkback}
            aria-label={talkback ? "Jarvis speaks replies. Turn off" : "Jarvis is muted. Turn on"}
            title={talkback ? "Speaking replies" : "Muted"}
          >
            <span aria-hidden>{talkback ? "\u{1F50A}" : "\u{1F507}"}</span>
          </button>
        )}
        {/* Which brain answered, what is stored, which devices are signed in —
            all of it lives behind this. The board is a readout, not a control
            panel. */}
        <button className="gear" onClick={() => setOpen("settings")} aria-label="Settings">
          <span aria-hidden>&#9881;</span>
        </button>
      </header>

      <main className="stage">
        <Dashboard
          token={token}
          jarvis={jarvis}
          voice={voice}
          onOpenChat={() => setOpen("chat")}
          onSettings={() => setOpen("settings")}
        />
      </main>

      {/* The answer where the question was asked. Never while the conversation
          is open — the log is already doing this job there, and two copies of
          the same sentence is worse than one. */}
      {open !== "chat" && (
        <Whisper
          log={jarvis.log}
          thinking={jarvis.state === "thinking"}
          onOpen={() => setOpen("chat")}
        />
      )}

      {open === "chat" && (
        <ChatSheet jarvis={jarvis} voice={voice} token={token} onClose={() => setOpen("none")} />
      )}
      {open === "search" && (
        <Search token={token} onClose={() => setOpen("none")} />
      )}
      {open === "settings" && (
        <Settings token={token} onClose={() => setOpen("none")} onSignOut={onForget} />
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
  // Keyed on the token so signing out and in again builds a fresh socket rather
  // than reusing one wired to a token that no longer works.
  return <Hud key={token} token={token} onForget={forget} />;
}
