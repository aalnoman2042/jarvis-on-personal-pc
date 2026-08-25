/* The conversation, as a HUD log rather than a chat app.
 *
 * A chat app is bubbles and avatars. This is a readout: fixed-width timestamps,
 * a source on every line, and system lines that look like the machine talking
 * rather than a person. Which is honest — a tool call is not Jarvis speaking.
 */
import { useEffect, useRef } from "react";

import type { LogLine } from "../lib/types";

function clock(at: number) {
  return new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function Log({ lines }: { lines: LogLine[] }) {
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    // Only follow along if you were already at the bottom. Auto-scrolling while
    // someone is reading back through the log is maddening.
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    if (atBottom) end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [lines]);

  if (!lines.length) {
    return (
      <div className="log log-empty" ref={box}>
        <p>
          <span className="label">Standing by</span>
          <br />
          Ask me something. I can search the web, remember things about you, set
          reminders, and drive your PC when it&rsquo;s awake.
        </p>
      </div>
    );
  }

  return (
    <div className="log" ref={box}>
      {lines.map((line) => (
        <div key={line.id} className={`line line-${line.who}`}>
          <span className="mono line-time">{clock(line.at)}</span>
          <span className="line-who label">
            {line.who === "you" ? "You" : line.who === "jarvis" ? line.brain || "Jarvis" : "sys"}
          </span>
          <span className="line-text">{line.text}</span>
        </div>
      ))}
      <div ref={end} />
    </div>
  );
}
