/* The conversation, as a drawer over the board.
 *
 * Full screen rather than a floating bubble: this is where you type, and typing
 * on a phone means the keyboard takes half the screen. A bubble would leave the
 * log two lines tall.
 *
 * Layout is `auto 1fr auto` — a bar you can close from, the log, the composer —
 * so the composer is pinned to the bottom and the log is the only thing that
 * scrolls. That is the same fix as on the board behind it, and for the same
 * reason: rows left on `auto` grow with the conversation until the box you are
 * typing into is off the screen.
 */
import { useEffect } from "react";

import { Composer } from "./Composer";
import { Log } from "./Log";
import type { Vondo } from "../lib/socket";
import type { Voice } from "../lib/voice";

export function ChatSheet({ jarvis, voice, onClose }: {
  jarvis: Vondo;
  voice: Voice;
  onClose: () => void;
}) {
  // Escape closes it on a desktop. On a phone the back gesture is the way out,
  // which the browser handles for the sheet being a route-less overlay only
  // because there is nothing to go back to — so the button is not optional.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="chat-sheet">
      <header className="chat-top">
        <span className={`conn conn-${jarvis.conn}`}>
          <span className="dot" aria-hidden />
          {voice.listening
            ? "Listening"
            : jarvis.state === "thinking"
              ? "Thinking"
              : jarvis.conn === "online"
                ? "Ready"
                : "Reconnecting"}
        </span>
        {jarvis.queued > 0 && (
          <span className="held label" title="Waiting for a connection">
            {jarvis.queued} held
          </span>
        )}
        <button className="linkish label chat-close" onClick={onClose}>Close</button>
      </header>

      {voice.error && <p className="mic-error label">{voice.error}</p>}
      <Log lines={jarvis.log} />
      <Composer onSay={jarvis.say} busy={jarvis.state === "thinking"} voice={voice} />
    </div>
  );
}
