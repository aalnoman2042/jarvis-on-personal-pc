/* The HUD's connection to Jarvis.
 *
 * A React hook around one websocket, with the awkward parts handled where they
 * belong rather than in a component:
 *
 *   * **Reconnects, with jittered backoff.** A phone on mobile data drops this
 *     socket constantly — walking into a lift, switching to wifi, locking the
 *     screen. Reconnecting has to be unremarkable, not an error state.
 *   * **Knows the difference between "no signal" and "not allowed".** A revoked
 *     token retried forever would hammer the server and never come back; that
 *     needs a person, so it stops and says so.
 *   * **Reconnects immediately when you come back.** Waiting out a backoff after
 *     unlocking your phone feels broken, so returning to the tab or regaining
 *     network skips straight to a retry.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { socketBase } from "./endpoint";
import * as outbox from "./outbox";
import type { ConnState, LogLine, ServerFrame, Telemetry } from "./types";
import type { ReactorState } from "../hud/reactorEngine";

const BACKOFF_START = 800;
const BACKOFF_MAX = 20000;

export interface Vondo {
  conn: ConnState;
  state: ReactorState;
  brain: string;
  pcOnline: boolean;
  telemetry: Telemetry;
  log: LogLine[];
  queued: number;
  say: (text: string) => void;
  note: (text: string) => void;
}

export function useVondo(token: string): Vondo {
  const [conn, setConn] = useState<ConnState>("connecting");
  const [state, setState] = useState<ReactorState>("offline");
  const [brain, setBrain] = useState("");
  const [pcOnline, setPcOnline] = useState(false);
  const [telemetry, setTelemetry] = useState<Telemetry>({});
  const [log, setLog] = useState<LogLine[]>([]);
  const [queued, setQueued] = useState(() => outbox.count());

  const socket = useRef<WebSocket | null>(null);
  const timer = useRef<number | null>(null);
  const backoff = useRef(BACKOFF_START);
  const nextId = useRef(1);
  // Kept in a ref as well as state: the socket's onclose runs outside React and
  // must not reconnect a socket we deliberately gave up on.
  const dead = useRef(false);

  const append = useCallback((who: LogLine["who"], text: string, extra?: Partial<LogLine>) => {
    setLog((lines) => [
      ...lines.slice(-199), // a day of talking should not become a memory leak
      { id: nextId.current++, who, text, at: Date.now(), ...extra },
    ]);
  }, []);

  const connect = useCallback(() => {
    if (!token || dead.current) return;
    const ws = new WebSocket(`${socketBase()}/ws/client?token=${encodeURIComponent(token)}`);
    socket.current = ws;
    setConn("connecting");

    ws.onopen = () => {
      backoff.current = BACKOFF_START;
      setConn("online");
      setState("online");

      // Anything typed while offline goes now, oldest first, and only leaves
      // the queue once it is actually on the wire. Sending is one at a time
      // because the server answers one turn at a time anyway, and a burst
      // would just queue up behind the brain lock.
      const waiting = outbox.read();
      if (waiting.length) {
        append("system", `Sending ${waiting.length} message${waiting.length > 1 ? "s" : ""} held while you were offline.`);
        for (const item of waiting) {
          try {
            ws.send(JSON.stringify({ type: "say", text: item.text }));
            outbox.remove(item.id);
          } catch {
            break; // socket went again; the rest stay queued
          }
        }
        setQueued(outbox.count());
      }
    };

    ws.onmessage = (event) => {
      let frame: ServerFrame;
      try {
        frame = JSON.parse(event.data);
      } catch {
        return;
      }
      switch (frame.type) {
        case "status":
          if (frame.brain) setBrain(frame.brain);
          if (typeof frame.pc_online === "boolean") setPcOnline(frame.pc_online);
          setState(frame.state === "thinking" ? "thinking" : "online");
          break;
        case "reply":
          setBrain(frame.brain);
          setPcOnline(frame.pc_online);
          setState("online");
          append("jarvis", frame.reply, { brain: frame.brain });
          break;
        case "telemetry":
          setTelemetry({
            cpu: frame.cpu,
            memory: frame.memory,
            battery: frame.battery,
            charging: frame.charging,
            ts: frame.ts,
          });
          break;
        case "error":
          setState("online");
          append("system", frame.error);
          break;
      }
    };

    ws.onclose = (event) => {
      socket.current = null;
      setState("offline");
      // 4401 is what the server closes with when the token is unknown or has
      // been revoked. Retrying that is pointless and noisy.
      if (event.code === 4401) {
        dead.current = true;
        setConn("unauthorised");
        return;
      }
      setConn("offline");
      const wait = backoff.current * (0.5 + Math.random());
      backoff.current = Math.min(backoff.current * 2, BACKOFF_MAX);
      timer.current = window.setTimeout(connect, wait);
    };

    ws.onerror = () => ws.close();
  }, [token, append]);

  useEffect(() => {
    dead.current = false;
    connect();

    // Coming back to the tab, or regaining network, should not wait out a
    // backoff that may be twenty seconds long.
    const nudge = () => {
      if (dead.current || socket.current) return;
      if (document.hidden) return;
      if (timer.current) window.clearTimeout(timer.current);
      backoff.current = BACKOFF_START;
      connect();
    };
    document.addEventListener("visibilitychange", nudge);
    window.addEventListener("online", nudge);

    return () => {
      document.removeEventListener("visibilitychange", nudge);
      window.removeEventListener("online", nudge);
      if (timer.current) window.clearTimeout(timer.current);
      dead.current = true;
      socket.current?.close();
      socket.current = null;
    };
  }, [connect]);

  const say = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      append("you", trimmed);
      const ws = socket.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        outbox.add(trimmed);
        setQueued(outbox.count());
        append("system", "No signal — held. I'll send it when you're back.");
        return;
      }
      setState("thinking");
      ws.send(JSON.stringify({ type: "say", text: trimmed }));
    },
    [append],
  );

  const note = useCallback((text: string) => append("system", text), [append]);

  return { conn, state, brain, pcOnline, telemetry, log, queued, say, note };
}
