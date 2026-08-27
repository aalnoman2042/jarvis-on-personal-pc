/* What was just said, floating over the board.
 *
 * The microphone has always been on the board, but the answer was not — it went
 * into the conversation, which is behind a button. So talking to Jarvis without
 * opening the chat meant hearing a reply you could not read, or reading nothing
 * at all if the phone was muted.
 *
 * This is the answer where the question was asked. It shows the last exchange
 * over the board, gets out of the way on its own, and never appears while the
 * conversation drawer is open — there the log is already doing this job, and two
 * copies of the same sentence is worse than one.
 *
 * **Swiping it away stops the voice too.** Pushing a reply off the screen means
 * "enough" — and having it carry on talking to an empty space is the single
 * most irritating thing a talking assistant can do. Dismissing is the one
 * gesture that has to silence it, so it does.
 *
 * Deliberately not a third place where history lives. It is a view of the last
 * two lines of the log, so there is still exactly one record of what was said.
 */
import { useEffect, useRef, useState } from "react";

import type { LogLine } from "../lib/types";
import * as speech from "../lib/speak";

/** Long enough to read a couple of sentences; short enough not to become
    furniture. Thinking does not count against it — the clock starts when the
    answer arrives. */
const LINGER_MS = 14000;

/** How far it has to move before it counts as a push rather than a tap. */
const SWIPE_PX = 55;

export function Whisper({ log, thinking, onOpen }: {
  log: LogLine[];
  thinking: boolean;
  onOpen: () => void;
}) {
  const [dismissed, setDismissed] = useState(0);
  const [drag, setDrag] = useState(0);
  const from = useRef<{ x: number; y: number } | null>(null);

  const lastYou = [...log].reverse().find((l) => l.who === "you");
  const lastJarvis = [...log].reverse().find((l) => l.who === "jarvis");
  const newest = log[log.length - 1];
  const id = newest?.id ?? 0;

  useEffect(() => {
    if (!id || thinking) return;
    const t = window.setTimeout(() => setDismissed(id), LINGER_MS);
    return () => window.clearTimeout(t);
  }, [id, thinking]);

  // A new answer arriving resets the drag, or the next one would come in
  // already pushed halfway off the screen.
  useEffect(() => {
    setDrag(0);
  }, [id]);

  function close() {
    // The point of the gesture. Reading on after being pushed away is the
    // single most irritating thing a talking assistant can do.
    speech.silence();
    setDismissed(id);
  }

  if (!id || dismissed === id) return null;
  if (!lastYou && !lastJarvis) return null;

  return (
    <div
      className="whisper bracket"
      role="button"
      tabIndex={0}
      style={
        drag
          ? {
              transform: `translate(${drag}px, 0)`,
              opacity: Math.max(0, 1 - Math.abs(drag) / 180),
              transition: "none",
            }
          : undefined
      }
      onPointerDown={(e) => {
        from.current = { x: e.clientX, y: e.clientY };
        (e.target as Element).setPointerCapture?.(e.pointerId);
      }}
      onPointerMove={(e) => {
        if (!from.current) return;
        const dx = e.clientX - from.current.x;
        const dy = e.clientY - from.current.y;
        // Sideways only. A vertical drag is the board scrolling underneath,
        // and stealing that would make the page feel stuck.
        if (Math.abs(dx) > Math.abs(dy)) setDrag(dx);
      }}
      onPointerUp={(e) => {
        const start = from.current;
        from.current = null;
        if (!start) return;
        const dx = e.clientX - start.x;
        if (Math.abs(dx) > SWIPE_PX) {
          close();
          return;
        }
        setDrag(0);
        // Barely moved: that was a tap, and a tap opens the conversation.
        if (Math.abs(dx) < 8 && Math.abs(e.clientY - start.y) < 8) onOpen();
      }}
      onPointerCancel={() => {
        from.current = null;
        setDrag(0);
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") close();
        if (e.key === "Enter" || e.key === " ") onOpen();
      }}
      aria-label="What was just said. Tap to open the conversation, swipe to dismiss"
    >
      {lastYou && <span className="whisper-you label">{lastYou.text}</span>}
      {thinking ? (
        <span className="whisper-said whisper-thinking">Thinking…</span>
      ) : (
        lastJarvis && <span className="whisper-said">{lastJarvis.text}</span>
      )}
      <span className="whisper-foot">
        <span className="whisper-more label">Tap to open · swipe to dismiss</span>
        <button
          className="whisper-x label"
          onClick={(e) => {
            e.stopPropagation();
            close();
          }}
          aria-label="Dismiss and stop speaking"
        >
          ✕
        </button>
      </span>
    </div>
  );
}
