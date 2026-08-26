/* The conversation, as a HUD log rather than a chat app.
 *
 * A chat app is bubbles and avatars. This is a readout: fixed-width timestamps,
 * a source on every line, and system lines that look like the machine talking
 * rather than a person. Which is honest — a tool call is not Jarvis speaking.
 */
import { useEffect, useRef, useState } from "react";

import type { LogLine } from "../lib/types";

function clock(at: number) {
  return new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/* What the archive gave up for this answer.
 *
 * Folded away by default and one tap from open. It matters because an answer
 * can be wrong two different ways — the model reasoned badly, or it was handed
 * the wrong memories — and without this there is no way to tell them apart.
 * Which also makes it the most FUI thing on the screen: a retrieval readout is
 * exactly the furniture the reference is full of, and this one is true.
 */
function Recalled({ items }: { items: { when: number; said: string }[] }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="recalled">
      <button className="recalled-tag label" onClick={() => setOpen((v) => !v)}>
        ⟲ recalled {items.length}
      </button>
      {open && (
        <ul className="recalled-list">
          {items.map((item, i) => (
            <li key={i}>
              <span className="mono recalled-when">
                {new Date(item.when * 1000).toLocaleDateString([], {
                  day: "numeric",
                  month: "short",
                })}
              </span>
              <span>{item.said}</span>
            </li>
          ))}
        </ul>
      )}
    </span>
  );
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

  // The keyboard opening takes a few hundred pixels off the log without moving
  // its scroll position, which leaves the newest line hidden above the fold at
  // the exact moment you are replying to it.
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;
    const pin = () => end.current?.scrollIntoView({ block: "end" });
    vv.addEventListener("resize", pin);
    return () => vv.removeEventListener("resize", pin);
  }, []);

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
            {line.who === "you" ? "You" : line.who === "jarvis" ? "Jarvis" : "sys"}
          </span>
          <span className="line-text">{line.text}</span>
          {line.recalled?.length ? <Recalled items={line.recalled} /> : null}
        </div>
      ))}
      <div ref={end} />
    </div>
  );
}
