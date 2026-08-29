/* The things Jarvis has been told to remember about Rohan.
 *
 * This was a sub-heading inside the Memory panel, underneath the exchange
 * count, and it did not belong there. The count is one number that never
 * changes shape; this is a list that grows to a dozen entries, each with its
 * own button — so the panel got taller as the list filled and pushed
 * notifications, the voice picker, the PC and the sign-out button off the
 * bottom of a phone screen. Two different kinds of thing in one box, and the
 * one you look at least crowded out the ones you act on.
 *
 * **Folded by default, with the count on the outside.** A settings screen is
 * something you glance at to check one thing. The number is what you want at a
 * glance — "it knows nine things about me" — and the nine sentences are what
 * you want only when you have come to change one.
 *
 * A few are shown while folded because a section that reveals nothing until
 * tapped gives you no reason to tap it.
 */
import { useState } from "react";

/** Shown while folded. Enough to recognise the list, few enough to stay short. */
const PEEK = 3;

export function Remembered({ facts, busy, onForget }: {
  facts: string[];
  busy: boolean;
  onForget: (fragment: string) => void;
}) {
  const [open, setOpen] = useState(false);

  if (!facts.length) {
    return (
      <section className="panel bracket">
        <span className="label">Remembered about you</span>
        <p className="muted small">
          Nothing yet. Say &ldquo;remember that&hellip;&rdquo; and it will keep
          it for good.
        </p>
      </section>
    );
  }

  const shown = open ? facts : facts.slice(0, PEEK);
  const hidden = facts.length - shown.length;

  return (
    <section className="panel bracket">
      <div className="brief-top">
        <span className="label">Remembered about you</span>
        {facts.length > PEEK && (
          <button className="linkish label" onClick={() => setOpen(!open)}>
            {open ? "Show fewer" : `Show all ${facts.length}`}
          </button>
        )}
      </div>

      <ul className="facts">
        {shown.map((fact) => (
          <li key={fact}>
            <span>{fact}</span>
            <button
              className="linkish label"
              disabled={busy}
              onClick={() => onForget(fact.slice(0, 40))}
              aria-label={`Forget: ${fact}`}
            >
              Forget
            </button>
          </li>
        ))}
      </ul>

      {hidden > 0 && (
        <p className="muted small">
          {hidden} more.
        </p>
      )}
    </section>
  );
}
