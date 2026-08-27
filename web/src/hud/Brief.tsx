/* The morning briefing.
 *
 * The one thing on the board Jarvis volunteers rather than answers. It takes the
 * top of the screen the first time you open the app on a new day, and steps out
 * of the way once you have read it — a briefing that greets you identically at
 * 9am and 9pm is wallpaper, and wallpaper is not read.
 *
 * "Read" is recorded on the server, per device, so dismissing it on the phone
 * does not silence it on the desktop and vice versa. It is a different morning
 * on each screen you actually look at.
 *
 * There is a way back in: the Today button re-reads it whenever you want. What
 * is gone is only the automatic one.
 */
import { useEffect, useState } from "react";

import { brief, briefSeen } from "../lib/api";
import * as speech from "../lib/speak";
import { SpeakButton } from "./SpeakButton";

export function Brief({ token, tick }: {
  token: string;
  /** Changes when something happened that could alter today — a new reminder,
      a finished turn — so the briefing is not stale by the time it is read. */
  tick: number;
}) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [asked, setAsked] = useState(false); // opened by hand, not by the day
  const [voiceNote, setVoiceNote] = useState("");

  useEffect(() => {
    let alive = true;
    brief(token)
      .then((data) => {
        if (!alive) return;
        setText(data.text);
        // Only unfold itself on a genuinely new day. Otherwise it waits behind
        // the button.
        if (data.fresh) setOpen(true);
      })
      .catch(() => {
        /* a briefing that cannot load is not worth an error on the board */
      });
    return () => {
      alive = false;
    };
  }, [token, tick]);

  function dismiss() {
    setOpen(false);
    setAsked(false);
    speech.silence();
    briefSeen(token).catch(() => {});
  }

  function show() {
    setAsked(true);
    setOpen(true);
  }

  if (!text) return null;

  if (!open) {
    return (
      <button className="brief-peek chip chip-quiet" onClick={show}>
        ▸ TODAY
      </button>
    );
  }

  return (
    <section className="panel bracket brief">
      <div className="brief-top">
        <span className="label">{asked ? "Today" : "Your briefing"}</span>
        <div className="brief-acts">
          <SpeakButton text={text} onNote={setVoiceNote} />
          <button className="linkish label" onClick={dismiss}>Dismiss</button>
        </div>
      </div>
      <p className="brief-text">{text}</p>
      {voiceNote && <p className="muted small">{voiceNote}</p>}
    </section>
  );
}
