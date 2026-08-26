/* The screen you land on: a status board, not a chat window.
 *
 * Chat was the home screen until now, which put an empty text field in front of
 * you every time you opened the app and made Jarvis something you had to
 * interrogate. A board answers the questions you actually open the app with —
 * what is coming up, is the PC awake, is anything wrong — before you ask any of
 * them. Talking to it is one tap away, on the button in the corner.
 *
 * Every number here is real and comes from the running system. Nothing is
 * modelled, estimated, or filled in for the look of the thing: an invented
 * figure rendered as a precise gauge is the fastest way to make a FUI feel fake,
 * and the fastest way to make the true numbers beside it untrustworthy.
 */
import { useEffect, useState } from "react";

import { Brief } from "../hud/Brief";
import { Dial } from "../hud/Dial";
import { Mail } from "../hud/Mail";
import { Reactor } from "../hud/Reactor";
import { Vision } from "../hud/Vision";
import { dropAgenda, me } from "../lib/api";
import { askPermission, syncAlarms } from "../lib/notify";
import type { Me } from "../lib/types";
import type { Vondo } from "../lib/socket";
import type { Voice } from "../lib/voice";

function greeting(hour: number): string {
  if (hour < 5) return "Still up";
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  if (hour < 22) return "Good evening";
  return "Good evening";
}

function ago(ts?: number | null): string {
  if (!ts) return "—";
  const mins = Math.floor((Date.now() - ts * 1000) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** The clock, ticking. Its own component so the minute rolling over repaints
    four lines of text rather than the whole board. */
function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    // Stops dead when the app is not on screen, which is the same rule the
    // reactor keeps. A twenty-second timer is not much, but "lightweight" was a
    // stated requirement and a timer nobody can see is pure waste.
    let timer = 0;
    const run = () => {
      window.clearInterval(timer);
      if (document.hidden) return;
      setNow(new Date());
      timer = window.setInterval(() => setNow(new Date()), 20_000);
    };
    run();
    document.addEventListener("visibilitychange", run);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", run);
    };
  }, []);
  return (
    <>
      <div className="clock-time mono">
        {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
      </div>
      <div className="clock-date label">
        {now.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })}
      </div>
    </>
  );
}

export function Dashboard({ token, jarvis, voice, onOpenChat, onSettings }: {
  token: string;
  jarvis: Vondo;
  voice: Voice;
  onOpenChat: () => void;
  onSettings: () => void;
}) {
  const [info, setInfo] = useState<Me | null>(null);

  async function load() {
    try {
      const next = await me(token);
      setInfo(next);
      // Hand the diary to the phone's own alarm clock. This is what makes a
      // reminder arrive with the app shut, the phone offline and the free-tier
      // server asleep — the three conditions the websocket cannot survive.
      syncAlarms(next.upcoming ?? []);
    } catch {
      // A board that cannot load is not an error worth a red banner: the socket
      // above it already says whether there is a connection at all.
    }
  }

  // Asked the first time there is something in the diary OR the first time the
  // board loads with an empty one and the app has been used a little — the old
  // rule required an existing reminder, which is a chicken and egg: nothing
  // asked, so nothing could ever arrive, so nobody found out until they missed
  // something. Android only ever asks once, so the timing still matters: this
  // waits for the app to be worth granting rather than prompting on launch.
  useEffect(() => {
    if (!info) return;
    if (info.upcoming?.length || (info.remembered ?? 0) > 3) askPermission();
  }, [info?.upcoming?.length, info?.remembered]);

  // Counted rather than watching the whole log: reloading on every line would
  // fetch twice per turn, once for the question and once for the answer, and
  // /me is half a dozen queries against a database on the other side of the
  // internet. An answer is the only half that can have changed anything.
  const answers = jarvis.log.filter((line) => line.who === "jarvis").length;

  useEffect(() => {
    load();
    // Reloading when a turn finishes keeps the counts and the diary in step with
    // a conversation that just changed them — "remind me on the 18th" appears in
    // UP NEXT without a manual refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, answers]);

  // Live telemetry beats whatever /me last saw; /me is the fallback for the
  // moment before the first frame arrives.
  const pc = info?.pc?.[0];
  const live = jarvis.telemetry;
  const cpu = live.cpu ?? pc?.telemetry?.cpu;
  const memory = live.memory ?? pc?.telemetry?.memory;
  const battery = live.battery ?? pc?.telemetry?.battery;
  const upcoming = info?.upcoming ?? [];
  const hour = new Date().getHours();
  const name = info?.user || "";

  async function drop(id: number) {
    try {
      const result = await dropAgenda(token, id);
      setInfo((prev) => (prev ? { ...prev, upcoming: result.items } : prev));
    } catch {
      /* leave it on screen; the next load will tell the truth */
    }
  }

  return (
    <div className="board">
      {jarvis.alert && (
        <button className="alert bracket" onClick={jarvis.dismiss}>
          <span className="label">Reminder</span>
          <span className="alert-text">{jarvis.alert.text}</span>
          <span className="label alert-x">Dismiss</span>
        </button>
      )}

      <Brief token={token} tick={answers} />

      <section className="hero">
        <div className="hero-reactor">
          {/* Listening is a local fact the server knows nothing about, so it
              overrides whatever the socket last said. The level is what makes
              the ring answer "can you hear me" without anyone asking. */}
          <Reactor
            state={voice.listening ? "listening" : jarvis.state}
            level={voice.listening ? voice.level : 0}
          />
        </div>
        <div className="hero-words">
          <h1 className="hero-greet">
            {greeting(hour)}
            {name ? <>, <span className="hero-name">{name}</span></> : null}
          </h1>
          <Clock />
        </div>
      </section>

      <div className="panels">
        <section className="panel bracket panel-wide">
          <span className="label">Up next</span>
          {upcoming.length ? (
            <ul className="agenda">
              {upcoming.map((item) => (
                <li key={item.id} className={`agenda-${item.kind}`}>
                  <span className="agenda-what">{item.message}</span>
                  <span className="agenda-when mono">
                    {item.said.replace(`${item.message} — `, "")}
                  </span>
                  <button className="linkish label" onClick={() => drop(item.id)}
                          aria-label={`Remove ${item.message}`}>
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted small">
              Nothing scheduled. Tell Jarvis &ldquo;I have an exam on the 18th&rdquo;
              and it will be here.
            </p>
          )}
        </section>

        <section className="panel bracket">
          <span className="label">Your PC</span>
          {jarvis.pcOnline ? (
            <>
              <h3 className="panel-head">
                {pc?.name || "Online"}
                <span className="chip chip-good panel-badge">LINKED</span>
              </h3>
              <div className="dials">
                <Dial label="CPU" value={cpu} />
                <Dial label="Memory" value={memory} />
                {typeof battery === "number" && (
                  <Dial label="Battery" value={battery} invert />
                )}
              </div>
            </>
          ) : (
            <>
              <h3 className="panel-head panel-off">Asleep</h3>
              <p className="muted small">
                Run <span className="mono">start_agent.bat</span> to open apps and
                read this machine from here.
              </p>
            </>
          )}
        </section>

        <section className="panel bracket">
          <span className="label">Memory</span>
          <h3 className="panel-head">{info?.remembered ?? "—"}</h3>
          <p className="muted small">exchanges, kept for good</p>
          <div className="chip-row">
            <span className="chip">SQLITE</span>
            <span className="chip">FTS5</span>
            <span className="chip chip-quiet">FOREVER</span>
          </div>
          <div className="stat-row">
            <span className="mono">{info?.facts?.length ?? 0}</span>
            <span className="muted small">things it knows about you</span>
          </div>
          <div className="stat-row">
            <span className="mono">{upcoming.length}</span>
            <span className="muted small">in the diary</span>
          </div>
        </section>

        <section className="panel bracket">
          <span className="label">Link</span>
          <h3 className="panel-head">{(jarvis.brain || info?.brain || "—").split("+")[0]}</h3>
          <p className="muted small">answering now</p>
          <div className="stat-row">
            <span className={`dot ${jarvis.conn === "online" ? "dot-on" : "dot-off"}`} aria-hidden />
            <span className="muted small">
              {jarvis.conn === "online" ? "cloud connected" : "reconnecting"}
            </span>
          </div>
          <div className="stat-row">
            <span className={`dot ${jarvis.pcOnline ? "dot-on" : "dot-off"}`} aria-hidden />
            <span className="muted small">{jarvis.pcOnline ? "PC awake" : "PC asleep"}</span>
          </div>
          <button className="linkish label panel-more" onClick={onSettings}>
            Settings →
          </button>
        </section>

        <Mail token={token} />

        <Vision token={token} />

        {info?.recent_actions?.length ? (
          <section className="panel bracket panel-wide">
            <span className="label">Recently done</span>
            <ul className="acts">
              {info.recent_actions.slice(0, 5).map((a, i) => (
                <li key={i}>
                  <span className="mono act-tool">{a.tool.replace(/_/g, " ")}</span>
                  <span className="muted small">{a.args || ""}</span>
                  <span className="muted small">{ago(a.ts)}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>

      {/* The way in to a conversation. Fixed to the corner so it is reachable
          with a thumb and never scrolls away. */}
      {/* The vitals, along the bottom, the way a command screen carries them:
          always there, never in the way. Every figure is read from the running
          system — there is nothing here for decoration. */}
      <div className="strip">
        <span>CORE <b>{jarvis.conn === "online" ? "LINKED" : "SYNC"}</b></span>
        <span>BRAIN <b>{(jarvis.brain || info?.brain || "—").split("+")[0].toUpperCase()}</b></span>
        <span>MEM <b>{info?.remembered ?? "—"}</b></span>
        <span>DIARY <b>{upcoming.length}</b></span>
        <span>NODES <b>{info?.devices?.filter((d) => !d.revoked).length ?? "—"}</b></span>
        <span className="strip-end">
          PC <b>{jarvis.pcOnline ? `${Math.round(cpu ?? 0)}% CPU` : "OFFLINE"}</b>
        </span>
      </div>

      {/* Two ways in, side by side: type, or just talk. The microphone works
          from the board itself — needing to open the conversation first would
          make the quick thing the slow one. */}
      <div className="fab-row">
        {voice.supported && (
          <button
            className={`fab fab-mic fab-mic-${voice.working ? "working" : voice.listening ? "on" : "off"}`}
            onClick={voice.toggle}
            disabled={voice.working}
            aria-label={voice.listening ? "Listening — tap to stop" : "Talk to Jarvis"}
            style={{ ["--mic-level" as string]: voice.listening ? voice.level.toFixed(2) : "0" }}
          >
            <span className="mic-ring" aria-hidden />
            <span aria-hidden>{voice.working ? "···" : "◉"}</span>
          </button>
        )}
        <button className="fab" onClick={onOpenChat} aria-label="Talk to Jarvis">
          <span className="fab-icon" aria-hidden>◈</span>
          <span className="fab-word label">Ask</span>
        </button>
      </div>
    </div>
  );
}
