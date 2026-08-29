/* The PC's screen, on the phone, with a finger on it.
 *
 * Rohan asked for this knowing what it costs: a mouse and a keyboard are every
 * action at once, so the allow-list and the confirm gates that protect the rest
 * of the system cannot protect this one. What is still true is that it asks
 * once at the desk before the first click (agent/guard.py), that every click is
 * written to the action log, and that it stops the moment you look away.
 *
 * **Frames are pulled, not streamed.** The next one is asked for when the last
 * has been drawn, which is what makes closing this sheet enough to stop
 * everything: there is no timer on the PC and no subscription on the server to
 * remember to cancel. A slow link means fewer frames rather than a queue that
 * grows until something falls over.
 *
 * **A tap is not a click until it has been shown to be one.** A finger is
 * fifty pixels wide and always moves a little, so the same gesture has to be
 * told apart by how far and how long it went: a still, brief touch is a click;
 * a still, long one is a right-click; a moving one is a scroll. Getting this
 * wrong does not produce a bad tap, it produces a drag across somebody's
 * desktop.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { screenFrame, screenInput } from "../lib/api";

/** Below this movement a touch was meant to be still. */
const STILL_PX = 12;
/** Held longer than this, a still touch is a right-click. */
const HOLD_MS = 500;
/** Never ask for frames faster than this, however quick the link is. */
const FLOOR_MS = 120;
/** After a failure, wait before trying again rather than hammering. */
const RETRY_MS = 1500;

/** Wire size. Small enough to be quick, large enough to read a menu. */
const WIDTHS = [
  { label: "Fast", width: 640, quality: 35 },
  { label: "Clear", width: 900, quality: 45 },
  { label: "Sharp", width: 1280, quality: 60 },
];

const KEYS: { label: string; send: string }[] = [
  { label: "Esc", send: "escape" },
  { label: "Tab", send: "tab" },
  { label: "↵", send: "enter" },
  { label: "⌫", send: "backspace" },
  { label: "Win", send: "win" },
  { label: "Alt+Tab", send: "alt+tab" },
  { label: "Ctrl+C", send: "ctrl+c" },
  { label: "Ctrl+V", send: "ctrl+v" },
];

export function Screen({ token, onClose }: { token: string; onClose: () => void }) {
  const [frame, setFrame] = useState("");
  const [size, setSize] = useState("");
  const [problem, setProblem] = useState("");
  const [quality, setQuality] = useState(1);
  const [typing, setTyping] = useState("");
  const [drag, setDrag] = useState(false);
  const [note, setNote] = useState("");

  const running = useRef(true);
  const picture = useRef<HTMLImageElement | null>(null);
  const level = useRef(quality);
  level.current = quality;

  // ---- pulling frames ---------------------------------------------------
  useEffect(() => {
    running.current = true;

    async function pump() {
      while (running.current) {
        if (document.visibilityState !== "visible") {
          // A viewer nobody is looking at must not keep the PC busy.
          await new Promise((r) => setTimeout(r, 400));
          continue;
        }
        const started = Date.now();
        try {
          const spec = WIDTHS[level.current];
          const data = await screenFrame(token, spec.width, spec.quality);
          if (!running.current) return;
          setFrame(data.image);
          setSize(data.size || "");
          setProblem("");
        } catch (err) {
          if (!running.current) return;
          setProblem(err instanceof Error ? err.message : "Lost the picture.");
          await new Promise((r) => setTimeout(r, RETRY_MS));
          continue;
        }
        const spent = Date.now() - started;
        if (spent < FLOOR_MS) {
          await new Promise((r) => setTimeout(r, FLOOR_MS - spent));
        }
      }
    }

    pump();
    const wake = () => { /* the loop checks visibility itself */ };
    document.addEventListener("visibilitychange", wake);
    return () => {
      running.current = false;
      document.removeEventListener("visibilitychange", wake);
    };
  }, [token]);

  const send = useCallback(
    async (kind: string, x = 0, y = 0, data = "") => {
      try {
        const result = await screenInput(token, kind, x, y, data);
        // "ok" is the only thing not worth saying out loud; everything else is
        // the PC explaining itself and is the whole reason it came back.
        setNote(result.said === "ok" ? "" : result.said || "");
      } catch (err) {
        setNote(err instanceof Error ? err.message : "That didn't reach your PC.");
      }
    },
    [token],
  );

  // ---- turning a touch into a mouse -------------------------------------
  const down = useRef<{ x: number; y: number; at: number } | null>(null);

  function where(e: React.PointerEvent<HTMLImageElement>): { x: number; y: number } {
    const box = e.currentTarget.getBoundingClientRect();
    // Fractions of the picture, so the PC's resolution never has to travel and
    // a frame scaled down for the wire still points at the right pixel.
    return {
      x: (e.clientX - box.left) / Math.max(1, box.width),
      y: (e.clientY - box.top) / Math.max(1, box.height),
    };
  }

  function onDown(e: React.PointerEvent<HTMLImageElement>) {
    const at = where(e);
    down.current = { x: at.x, y: at.y, at: Date.now() };
  }

  function onUp(e: React.PointerEvent<HTMLImageElement>) {
    const start = down.current;
    down.current = null;
    if (!start) return;
    const end = where(e);
    const box = e.currentTarget.getBoundingClientRect();
    const moved = Math.hypot(
      (end.x - start.x) * box.width, (end.y - start.y) * box.height);
    const held = Date.now() - start.at;

    if (moved > STILL_PX) {
      if (drag) {
        send("drag", end.x, end.y, `${start.x},${start.y}`);
      } else {
        // Vertical movement is a scroll. Positive scrolls up on Windows, and a
        // finger moving DOWN should move the page down, hence the sign.
        const notches = Math.round((start.y - end.y) * 12);
        if (notches) send("scroll", 0, notches);
      }
      return;
    }
    send(held >= HOLD_MS ? "right" : "click", end.x, end.y);
  }

  return (
    <div className="sheet screen-sheet">
      <header className="sheet-top">
        <span className="label">
          Your PC{size && <span className="muted small mono"> · {size}</span>}
        </span>
        <div className="brief-acts">
          <button
            className={`linkish label${drag ? " device-sure" : ""}`}
            onClick={() => setDrag(!drag)}
            aria-pressed={drag}
            title={drag ? "Swiping drags" : "Swiping scrolls"}
          >
            {drag ? "Drag" : "Scroll"}
          </button>
          <button
            className="linkish label"
            onClick={() => setQuality((quality + 1) % WIDTHS.length)}
          >
            {WIDTHS[quality].label}
          </button>
          <button className="linkish label" onClick={onClose}>Close</button>
        </div>
      </header>

      <div className="screen-stage">
        {frame ? (
          <img
            ref={picture}
            className="screen-picture"
            src={frame}
            alt="Your PC's screen"
            draggable={false}
            onPointerDown={onDown}
            onPointerUp={onUp}
            onPointerCancel={() => { down.current = null; }}
          />
        ) : (
          <p className="muted small">
            {problem || "Waiting for the first picture…"}
          </p>
        )}
      </div>

      <div className="screen-keys">
        {KEYS.map((k) => (
          <button key={k.send} className="chip chip-quiet"
                  onClick={() => send("key", 0, 0, k.send)}>
            {k.label}
          </button>
        ))}
      </div>

      <form
        className="screen-typing bracket"
        onSubmit={(e) => {
          e.preventDefault();
          const text = typing;
          setTyping("");
          if (text) send("type", 0, 0, text);
        }}
      >
        <input
          value={typing}
          onChange={(e) => setTyping(e.target.value)}
          placeholder="Type on the PC, then send…"
          aria-label="Text to type on the PC"
        />
        <button className="linkish label" type="submit">Send</button>
      </form>

      {(problem || note) && (
        <p className="muted small screen-note">{problem || note}</p>
      )}
    </div>
  );
}
