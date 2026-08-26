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
 * Deliberately not a third place where history lives. It is a view of the last
 * two lines of the log, so there is still exactly one record of what was said.
 */
import { useEffect, useState } from "react";

import type { LogLine } from "../lib/types";

/** Long enough to read a couple of sentences; short enough not to become
    furniture. Thinking does not count against it — the clock starts when the
    answer arrives. */
const LINGER_MS = 14000;

export function Whisper({ log, thinking, onOpen }: {
  log: LogLine[];
  thinking: boolean;
  onOpen: () => void;
}) {
  const [dismissed, setDismissed] = useState(0);

  const lastYou = [...log].reverse().find((l) => l.who === "you");
  const lastJarvis = [...log].reverse().find((l) => l.who === "jarvis");
  const newest = log[log.length - 1];
  const id = newest?.id ?? 0;

  useEffect(() => {
    if (!id || thinking) return;
    const t = window.setTimeout(() => setDismissed(id), LINGER_MS);
    return () => window.clearTimeout(t);
  }, [id, thinking]);

  if (!id || dismissed === id) return null;
  // Nothing to show until something has actually been said this session.
  if (!lastYou && !lastJarvis) return null;

  return (
    <button
      className="whisper bracket"
      onClick={onOpen}
      aria-label="Open the conversation"
    >
      {lastYou && <span className="whisper-you label">{lastYou.text}</span>}
      {thinking ? (
        <span className="whisper-said whisper-thinking">Thinking…</span>
      ) : (
        lastJarvis && <span className="whisper-said">{lastJarvis.text}</span>
      )}
      <span className="whisper-more label">Tap for the whole conversation</span>
    </button>
  );
}
