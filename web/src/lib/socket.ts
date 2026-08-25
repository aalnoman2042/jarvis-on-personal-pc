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
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${scheme}//${location.host}/ws/client?token=${encodeURIComponent(token)}`);
    socket.current = ws;
    setConn("connecting");

    ws.onopen = () => {
      backoff.current = BACKOFF_START;
      setConn("online");
      setState("online");
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
        append("system", "No connection to Jarvis — that one didn't send.");
        return;
      }
      setState("thinking");
      ws.send(JSON.stringify({ type: "say", text: trimmed }));
    },
    [append],
  );

  const note = useCallback((text: string) => append("system", text), [append]);

  return { conn, state, brain, pcOnline, telemetry, log, say, note };
}
