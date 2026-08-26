/* The microphone button.
 *
 * It shows three things at once, because all three matter while you are talking
 * to something that cannot nod: that it is listening, that it can hear you, and
 * that it is thinking about what you said. The ring around it is the live level
 * — not decoration, but the answer to "is this thing picking me up", which is
 * the question you silently ask every voice interface.
 */
import type { Voice } from "../lib/voice";

export function Mic({ voice }: { voice: Voice }) {
  if (!voice.supported) return null;

  const state = voice.working ? "working" : voice.listening ? "on" : "off";
  const label = voice.working
    ? "Working out what you said"
    : voice.listening
      ? "Listening — tap to stop"
      : "Talk to Jarvis";

  return (
    <button
      type="button"
      className={`mic mic-${state}`}
      onClick={voice.toggle}
      disabled={voice.working}
      aria-label={label}
      title={label}
      // Drives the ring. A CSS variable rather than a style rebuild, so sixty
      // updates a second do not become sixty React renders.
      style={{ ["--mic-level" as string]: voice.listening ? voice.level.toFixed(2) : "0" }}
    >
      <span className="mic-ring" aria-hidden />
      <span className="mic-glyph" aria-hidden>
        {voice.working ? "···" : "◉"}
      </span>
    </button>
  );
}
