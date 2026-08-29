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
 * **The problem is precision, not size.** A 1600x900 desktop drawn 360 pixels
 * wide puts about four and a half desktop pixels behind every phone pixel, so a
 * fingertip covers roughly two hundred of them — wider than most buttons and
 * far wider than a checkbox. Making the picture "bigger" cannot fix that on a
 * phone-sized screen; being able to magnify part of it can. Hence pinch, pan,
 * and a frame that is requested sharper as you zoom in, because magnifying a
 * 640-pixel-wide JPEG just shows you larger blur.
 *
 * **Two fingers move the view, one finger touches the PC.** A clean split with
 * no mode to remember and no toggle to get wrong: navigating never reaches the
 * desktop, and touching never moves the picture. It also means a pinch can
 * never be mistaken for a drag across somebody's desktop.
 *
 * **A tap is not a click until it has been shown to be one.** A finger is fifty
 * pixels wide and always moves a little, so the same gesture is told apart by
 * how far and how long it went: still and brief is a click, still and held is a
 * right-click, moving is a scroll.
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

const MIN_ZOOM = 1;
const MAX_ZOOM = 6;
/** The server clamps here too; asking for more is wasted bytes. */
const MAX_WIRE = 1280;

/** Wire size at 1x. Zooming in raises it — see `wireWidth`. */
const QUALITIES = [
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

type View = { scale: number; x: number; y: number };
const FIT: View = { scale: 1, x: 0, y: 0 };

export function Screen({ token, onClose }: { token: string; onClose: () => void }) {
  const [frame, setFrame] = useState("");
  const [size, setSize] = useState("");
  const [problem, setProblem] = useState("");
  const [quality, setQuality] = useState(1);
  const [typing, setTyping] = useState("");
  const [drag, setDrag] = useState(false);
  const [bare, setBare] = useState(false);
  const [note, setNote] = useState("");
  const [view, setView] = useState<View>(FIT);

  const running = useRef(true);
  const level = useRef(quality);
  level.current = quality;
  const zoom = useRef(view.scale);
  zoom.current = view.scale;

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
          const spec = QUALITIES[level.current];
          // Sharper as you magnify: zooming into a 640px frame shows bigger
          // blur, not more detail, and the whole point of zooming here is to
          // see something small clearly enough to hit it.
          const width = Math.min(
            MAX_WIRE, Math.round(spec.width * Math.max(1, zoom.current)));
          const data = await screenFrame(token, width, spec.quality);
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
    return () => { running.current = false; };
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

  // ---- gestures ---------------------------------------------------------
  const touches = useRef(new Map<number, { x: number; y: number }>());
  const start = useRef<{ x: number; y: number; at: number } | null>(null);
  const pinch = useRef<{ gap: number; view: View } | null>(null);

  function fraction(e: { clientX: number; clientY: number },
                    el: HTMLElement): { x: number; y: number } {
    // getBoundingClientRect reports the box AFTER the CSS transform, so the
    // same arithmetic keeps working at any zoom or pan without correction.
    // That is the reason the transform is on the image rather than a wrapper.
    const box = el.getBoundingClientRect();
    return {
      x: (e.clientX - box.left) / Math.max(1, box.width),
      y: (e.clientY - box.top) / Math.max(1, box.height),
    };
  }

  function clamp(next: View): View {
    const scale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, next.scale));
    // Do not let the picture be dragged off into empty space: at scale s there
    // is (s-1)/2 of a screen of slack in each direction, and no more.
    const slack = (scale - 1) / 2;
    const limitX = slack * 100, limitY = slack * 100;
    return {
      scale,
      x: Math.min(limitX, Math.max(-limitX, scale === 1 ? 0 : next.x)),
      y: Math.min(limitY, Math.max(-limitY, scale === 1 ? 0 : next.y)),
    };
  }

  function onDown(e: React.PointerEvent<HTMLImageElement>) {
    e.currentTarget.setPointerCapture?.(e.pointerId);
    touches.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (touches.current.size === 1) {
      const at = fraction(e, e.currentTarget);
      start.current = { x: at.x, y: at.y, at: Date.now() };
    } else if (touches.current.size === 2) {
      // A second finger cancels whatever the first was going to do. Otherwise
      // beginning a pinch also clicks wherever the first finger happened to be.
      start.current = null;
      const [a, b] = [...touches.current.values()];
      pinch.current = { gap: Math.hypot(a.x - b.x, a.y - b.y), view };
    }
  }

  function onMove(e: React.PointerEvent<HTMLImageElement>) {
    if (!touches.current.has(e.pointerId)) return;
    const before = touches.current.get(e.pointerId)!;
    touches.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (touches.current.size !== 2 || !pinch.current) return;

    const [a, b] = [...touches.current.values()];
    const gap = Math.hypot(a.x - b.x, a.y - b.y);
    const from = pinch.current;
    const box = e.currentTarget.getBoundingClientRect();
    setView(clamp({
      scale: from.view.scale * (gap / Math.max(1, from.gap)),
      // Two fingers also pan, in percent of the box so the transform stays
      // resolution-independent.
      x: view.x + ((e.clientX - before.x) / Math.max(1, box.width)) * 100,
      y: view.y + ((e.clientY - before.y) / Math.max(1, box.height)) * 100,
    }));
  }

  function onUp(e: React.PointerEvent<HTMLImageElement>) {
    const wasPinching = touches.current.size >= 2;
    touches.current.delete(e.pointerId);
    if (touches.current.size === 0) pinch.current = null;
    if (wasPinching) { start.current = null; return; }

    const from = start.current;
    start.current = null;
    if (!from) return;

    const end = fraction(e, e.currentTarget);
    const box = e.currentTarget.getBoundingClientRect();
    const moved = Math.hypot(
      (end.x - from.x) * box.width, (end.y - from.y) * box.height);
    const held = Date.now() - from.at;

    if (moved > STILL_PX) {
      if (drag) {
        send("drag", end.x, end.y, `${from.x},${from.y}`);
      } else {
        // A finger moving DOWN should move the page down, hence the sign.
        const notches = Math.round((from.y - end.y) * 12);
        if (notches) send("scroll", 0, notches);
      }
      return;
    }
    send(held >= HOLD_MS ? "right" : "click", end.x, end.y);
  }

  const zoomed = view.scale > 1.01;

  return (
    <div className={`sheet screen-sheet${bare ? " screen-bare" : ""}`}>
      <header className="sheet-top">
        <span className="label">
          PC{size && <span className="muted small mono"> · {size}</span>}
          {zoomed && <span className="muted small mono"> · {view.scale.toFixed(1)}×</span>}
        </span>
        <div className="brief-acts">
          {zoomed && (
            <button className="linkish label" onClick={() => setView(FIT)}>Fit</button>
          )}
          <button
            className={`linkish label${drag ? " device-sure" : ""}`}
            onClick={() => setDrag(!drag)}
            aria-pressed={drag}
            title={drag ? "Swiping drags on the PC" : "Swiping scrolls the PC"}
          >
            {drag ? "Drag" : "Scroll"}
          </button>
          <button
            className="linkish label"
            onClick={() => setQuality((quality + 1) % QUALITIES.length)}
          >
            {QUALITIES[quality].label}
          </button>
          {/* Hides the key rows so the picture gets the whole screen. On a
              phone those three rows are a third of the height. */}
          <button
            className={`linkish label${bare ? " device-sure" : ""}`}
            onClick={() => setBare(!bare)}
            aria-pressed={bare}
            title={bare ? "Show the keyboard rows" : "Give the picture the whole screen"}
          >
            {bare ? "Keys" : "Big"}
          </button>
          <button className="linkish label" onClick={onClose}>Close</button>
        </div>
      </header>

      <div className="screen-stage">
        {frame ? (
          <img
            className="screen-picture"
            src={frame}
            alt="Your PC's screen"
            draggable={false}
            style={{
              transform: `translate(${view.x}%, ${view.y}%) scale(${view.scale})`,
            }}
            onPointerDown={onDown}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerCancel={(e) => {
              touches.current.delete(e.pointerId);
              start.current = null;
              pinch.current = null;
            }}
          />
        ) : (
          <p className="muted small">
            {problem || "Waiting for the first picture…"}
          </p>
        )}
      </div>

      {!bare && (
        <>
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
        </>
      )}

      {(problem || note) && (
        <p className="muted small screen-note">{problem || note}</p>
      )}
      {!frame && !problem && (
        <p className="muted small screen-note">
          One finger touches the PC · two fingers pinch and move the view
        </p>
      )}
    </div>
  );
}
