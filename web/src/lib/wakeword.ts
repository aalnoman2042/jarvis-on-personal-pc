/* Deciding whether somebody said "Jarvis".
 *
 * Split out from `listen.ts` deliberately: everything here is pure and imports
 * nothing, which is what lets it be compiled on its own and checked by
 * `tests/test_wakeword.mjs` without a browser, a test framework or a new
 * dependency. The hook next door is browser plumbing; this is the part with a
 * decision in it, and the part that will be wrong first.
 *
 * **The failure mode is waking when it should not.** A missed wake word is
 * mildly annoying and you say it again. A false wake takes a sentence you said
 * to somebody else and sends it to an assistant that can open applications. So
 * the tolerance is deliberately narrow, and the words it is NOT allowed to
 * accept are pinned in the test.
 *
 * "Jarvis" is a bad wake word in exactly one way: English has "service" and
 * "harvest" in it, both plausible things to say and both things a recogniser
 * offers when it is unsure. They are four edits away, so a tolerance of two
 * keeps them out while still catching jervis, javis, jarvus, harvis and darvis
 * — the shapes that actually come back.
 */

/** The word itself. */
export const WAKE = "jarvis";

/** How far a heard word may be from it. See the note above before raising. */
export const MAX_EDITS = 2;

/** Shorter than this and an edit distance of two means almost nothing. */
export const MIN_LEN = 5;

/** How wide the net is for RECORDING a near miss — wider than for accepting. */
export const MISS_EDITS = MAX_EDITS + 2;

export function distance(a: string, b: string, cap: number = MAX_EDITS): number {
  /* Ordinary Levenshtein, one row at a time. Both strings are one word long and
   * this runs a handful of times per utterance, so there is nothing here worth
   * optimising.
   *
   * `cap` is not a micro-optimisation, it is correctness. The early exit has to
   * return something ABOVE whatever the caller will accept, and the two callers
   * accept different amounts — accepting a wake at 2, recording a near miss at
   * 4. Returning a fixed `MAX_EDITS + 1` meant every long word came back as 3,
   * which the near-miss check read as "close", so "extraordinarily" would have
   * been logged as an almost-Jarvis. */
  if (Math.abs(a.length - b.length) > cap) return cap + 1;
  let prev: number[] = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const row: number[] = [i];
    for (let j = 1; j <= b.length; j++) {
      row[j] = Math.min(
        prev[j] + 1,
        row[j - 1] + 1,
        prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
    }
    prev = row;
  }
  return prev[b.length];
}

/** Just the words, lowercased. Punctuation carries nothing here. */
export function words(text: string): string[] {
  return (text || "").toLowerCase().match(/[a-z']+/g) || [];
}

export interface Woken {
  /** What was said after the wake word. Empty when it was said on its own. */
  command: string;
  /** The word that actually matched, so a near miss can be shown as one. */
  heard: string;
}

/** Find the wake word and return whatever followed it in the same breath.
 *
 * The command and the wake word arrive together — "Jarvis, what's on today" is
 * one utterance, not two — so waiting for the next one would drop half of what
 * anybody naturally says.
 *
 * Only the FIRST match counts. "Jarvis, ask Jarvis about Jarvis" is one
 * instruction, and treating each occurrence as a fresh wake would truncate it
 * to the last two words.
 */
export function wake(transcript: string): Woken | null {
  const said = words(transcript);
  for (let i = 0; i < said.length; i++) {
    const word = said[i];
    if (word.length < MIN_LEN) continue;
    if (word === WAKE || distance(word, WAKE) <= MAX_EDITS) {
      return { command: said.slice(i + 1).join(" ").trim(), heard: word };
    }
  }
  return null;
}

/** The near-miss word in an utterance that did NOT wake it, if there was one.
 *
 * Recorded so the tolerance can be widened from what a recogniser really
 * produces for this voice, in this room, rather than from a list somebody
 * imagined. Only the single word is kept — never the sentence it sat in.
 */
export function nearMiss(transcript: string): string {
  for (const word of words(transcript)) {
    if (word.length < MIN_LEN) continue;
    const d = distance(word, WAKE, MISS_EDITS);
    if (d > MAX_EDITS && d <= MISS_EDITS) return word;
  }
  return "";
}
