/* The week, looked back on.
 *
 * The briefing above it answers "what is today". This answers "what has
 * actually been happening", which is the one you cannot answer for yourself —
 * a week is exactly long enough to misremember and short enough to feel sure
 * about.
 *
 * It appears once, on the first open of a new week, and then waits behind a
 * chip. Weekly means weekly: a look-back that greets you every morning is a
 * daily report with a wrong name on it, and stops being read by Wednesday.
 *
 * Every number in it was counted, never estimated — see core/weekly.py. That is
 * what makes it safe to put on the board next to the gauges.
 */
import { useEffect, useState } from "react";

import { weekly, weeklySeen } from "../lib/api";
import * as speech from "../lib/speak";
import { SpeakButton } from "./SpeakButton";

type Figures = {
  finished: string[];
  added: number;
  still_open: number;
  overdue: number;
  conversations: number;
};

export function Weekly({ token, refresh }: { token: string; refresh?: number }) {
  const [text, setText] = useState("");
  const [figures, setFigures] = useState<Figures | null>(null);
  const [open, setOpen] = useState(false);
  const [asked, setAsked] = useState(false);
  const [note, setNote] = useState("");

  useEffect(() => {
    let alive = true;
    weekly(token)
      .then((data) => {
        if (!alive) return;
        setText(data.text);
        setFigures(data.figures);
        if (data.fresh) setOpen(true);
      })
      .catch(() => {
        /* a look-back that cannot load is not worth an error on the board */
      });
    return () => {
      alive = false;
    };
    /* Keyed on the token alone, deliberately. The briefing above reloads
       after every turn because today's diary can change mid-conversation; a
       look-back at the last seven days cannot meaningfully move while you are
       talking, and refetching it each turn is seven queries for nothing. */
  }, [token, refresh]);

  function dismiss() {
    setOpen(false);
    setAsked(false);
    setNote("");
    speech.silence();
    weeklySeen(token).catch(() => {});
  }

  if (!text) return null;

  if (!open) {
    return (
      <button
        className="brief-peek chip chip-quiet"
        onClick={() => {
          setAsked(true);
          setOpen(true);
        }}
      >
        ▸ THIS WEEK
      </button>
    );
  }

  const done = figures ? figures.finished.length : 0;

  return (
    <section className="panel bracket brief weekly">
      <div className="brief-top">
        <span className="label">{asked ? "This week" : "Your week"}</span>
        <div className="brief-acts">
          <SpeakButton text={text} onNote={setNote} />
          <button className="linkish label" onClick={dismiss}>Dismiss</button>
        </div>
      </div>

      {figures && (
        /* The three numbers the sentences are built from, shown beside them.
           A claim about your own week that you cannot check against anything
           is one you either accept on faith or ignore, and neither is useful. */
        <div className="weekly-figures">
          <span><b className="mono">{done}</b> done</span>
          <span><b className="mono">{figures.added}</b> added</span>
          <span><b className="mono">{figures.still_open}</b> open</span>
          {figures.overdue > 0 && (
            <span className="weekly-late">
              <b className="mono">{figures.overdue}</b> overdue
            </span>
          )}
        </div>
      )}

      <p className="brief-text">{text}</p>
      {note && <p className="muted small">{note}</p>}
    </section>
  );
}
