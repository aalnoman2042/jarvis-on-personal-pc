/* What Jarvis has learned about reading Rohan, as opposed to facts about him.
 *
 * "Remembered about you" is what he told it. This is what it got WRONG and was
 * corrected on — and it is shown for one reason: these go into the prompt as
 * instructions the model follows over its own judgement, so something learned
 * wrongly quietly changes answers. Anything with that much reach has to be
 * visible and removable, or it is a black box that gets blamed for everything.
 *
 * Taught and noticed are marked differently on purpose. One is Rohan saying
 * outright what he means; the other is Jarvis inferring it from a correction,
 * which is a guess and should look like one.
 */
import { useState } from "react";

type Correction = {
  id: number;
  asked: string;
  did: string;
  meant: string;
  source: string;
  ts: number;
  hits: number;
};

const PEEK = 3;

export function Corrections({ items, busy, onForget }: {
  items: Correction[];
  busy: boolean;
  onForget: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);

  if (!items.length) {
    return (
      <section className="panel bracket">
        <span className="label">Learned from corrections</span>
        <p className="muted small">
          Nothing yet. Say &ldquo;no, I meant&hellip;&rdquo; when it gets
          something wrong, or tell it outright &mdash; &ldquo;when I say move
          it, change the time rather than making a new one&rdquo;.
        </p>
      </section>
    );
  }

  const shown = open ? items : items.slice(0, PEEK);

  return (
    <section className="panel bracket">
      <div className="brief-top">
        <span className="label">Learned from corrections</span>
        {items.length > PEEK && (
          <button className="linkish label" onClick={() => setOpen(!open)}>
            {open ? "Show fewer" : `Show all ${items.length}`}
          </button>
        )}
      </div>

      <ul className="facts">
        {shown.map((c) => (
          <li key={c.id}>
            <span>
              {c.asked && (
                <span className="muted small">when you say &ldquo;{c.asked}&rdquo; · </span>
              )}
              {c.meant}
              {c.hits > 1 && (
                <span className="muted small"> · came up {c.hits}×</span>
              )}
            </span>
            <span className="device-right">
              <span className={`chip chip-quiet${c.source === "taught" ? " ear-on" : ""}`}>
                {c.source === "taught" ? "TOLD" : "NOTICED"}
              </span>
              <button
                className="linkish label"
                disabled={busy}
                onClick={() => onForget(c.id)}
                aria-label={`Unlearn: ${c.meant}`}
              >
                Unlearn
              </button>
            </span>
          </li>
        ))}
      </ul>
      <p className="muted small">
        These go into the prompt as instructions, so an unlearn takes effect on
        the next thing you say.
      </p>
    </section>
  );
}
