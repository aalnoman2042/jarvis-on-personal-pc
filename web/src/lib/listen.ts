/* Waiting to be spoken to.
 *
 * The mic already existed — `voice.ts` records a clip when you tap, sends it to
 * Whisper and hands back the words. This is the other half: while the app is
 * open it listens all the time, and saying "Jarvis" is what turns a sentence in
 * the room into a sentence addressed to it.
 *
 * **Chrome's own recogniser, not Whisper, and that is a deliberate reversal.**
 * `voice.ts` avoids `SpeechRecognition` on purpose, because the Capacitor
 * WebView the APK ran in usually does not have it, and a mic that worked in the
 * browser and not in the app would be worse than one that behaved the same
 * everywhere. That reasoning was correct and no longer applies: the app is an
 * installed PWA in Chrome now, which has the API. It also has to be Chrome's,
 * because always-on listening through Whisper means uploading every utterance
 * in the room — the free tier would be gone by lunchtime, and most of what it
 * paid for was somebody else's conversation.
 *
 * The tap-to-talk path stays exactly as it was, and is the fallback wherever
 * this API is missing.
 *
 * Four rules:
 *
 * **Nothing is kept unless you woke it.** Continuous listening in a room hears
 * things that are not for Jarvis. An utterance without the wake word is matched,
 * discarded, and never leaves the browser — no upload, no database, no log.
 *
 * **It must not hear itself.** Recognition stops while Jarvis is speaking. Left
 * running it transcribes its own reply, and a reply containing its own name
 * wakes it again — a loop that is very hard to interrupt once it starts.
 *
 * **It stops dead when the tab is hidden.** Same rule the reactor keeps. An
 * always-on microphone is the most expensive thing this app could possibly do,
 * and a tab nobody is looking at has no business holding one.
 *
 * **Near misses are recorded, not guessed at.** "Jarvis" is misheard constantly
 * and what it is misheard AS depends on the voice, the accent and the room. So
 * the matcher is deliberately conservative and every close-but-rejected phrase
 * is kept — in memory, for the settings screen — so the list can be widened
 * from evidence instead of from imagination. The alternative is picking a
 * tolerance now and discovering in a month that it wakes on "service".
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { nearMiss, wake } from "./wakeword";

/** How long it keeps listening for a follow-up after answering. */
export const AWAKE_MS = 10000;

/** Phrases that were close to the wake word but not close enough.
 *
 * In memory only, and only the single word — never the sentence it sat in. It
 * exists so the tolerance can be widened from what a recogniser really produces
 * for this voice and this room, instead of from a list somebody imagined.
 */
const misses: { word: string; at: number }[] = [];

export function nearMisses(): { word: string; at: number }[] {
  return misses.slice(-12);
}

type Recogniser = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((e: never) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error?: string }) => void) | null;
};

function build(): Recogniser | null {
  const w = window as unknown as {
    SpeechRecognition?: new () => Recogniser;
    webkitSpeechRecognition?: new () => Recogniser;
  };
  const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition;
  return Ctor ? new Ctor() : null;
}

export function supported(): boolean {
  const w = window as unknown as { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown };
  return Boolean(w.SpeechRecognition || w.webkitSpeechRecognition);
}

export interface Ears {
  supported: boolean;
  /** The toggle is on and the tab is visible, so it is actually listening. */
  listening: boolean;
  /** Woken, and taking the next thing said as a command. */
  awake: boolean;
  /** Empty unless something needs saying — a refused permission, mostly. */
  error: string;
  on: boolean;
  setOn: (value: boolean) => void;
}

export function useWakeWord({ enabled, speaking, onCommand }: {
  enabled: boolean;
  /** True while Jarvis is talking, so it does not transcribe its own voice. */
  speaking: boolean;
  onCommand: (text: string) => void;
}): Ears {
  const [on, setOn] = useState(enabled);
  const [listening, setListening] = useState(false);
  const [awake, setAwake] = useState(false);
  const [error, setError] = useState("");

  const rec = useRef<Recogniser | null>(null);
  const wanted = useRef(false);        // should it be running right now?
  const awakeUntil = useRef(0);
  const command = useRef(onCommand);
  command.current = onCommand;

  const handle = useCallback((text: string) => {
    const said = (text || "").trim();
    if (!said) return;

    const hit = wake(said);
    if (hit) {
      awakeUntil.current = Date.now() + AWAKE_MS;
      setAwake(true);
      // The rest of the same breath is the command. Said on its own, it just
      // opens the window and waits.
      if (hit.command) {
        awakeUntil.current = 0;
        setAwake(false);
        command.current(hit.command);
      }
      return;
    }

    // Already awake: a follow-up needs no second "Jarvis". The window is short
    // on purpose — long enough to ask one more thing, not long enough for a
    // passing remark to become an instruction.
    if (Date.now() < awakeUntil.current) {
      awakeUntil.current = 0;
      setAwake(false);
      command.current(said);
      return;
    }

    // Not for Jarvis. Nothing is uploaded, stored or written down — only the
    // shape of a near miss is kept, so the tolerance can be tuned on evidence.
    const close = nearMiss(said);
    if (close) {
      misses.push({ word: close, at: Date.now() });
      if (misses.length > 40) misses.shift();
    }
  }, []);

  useEffect(() => {
    if (!supported()) return;

    const start = () => {
      if (!wanted.current || rec.current) return;
      const r = build();
      if (!r) return;
      r.continuous = true;
      r.interimResults = false;
      r.lang = "en-IN";        // same as the legacy recogniser used
      r.onresult = (event: never) => {
        const e = event as unknown as {
          resultIndex: number;
          results: { [i: number]: { [j: number]: { transcript: string } }; length: number };
        };
        for (let i = e.resultIndex; i < e.results.length; i++) {
          handle(e.results[i][0].transcript);
        }
      };
      r.onerror = (e) => {
        // "no-speech" and "aborted" are ordinary and constant; only a refused
        // permission is worth telling anyone about, and it is fatal.
        if (e.error === "not-allowed" || e.error === "service-not-allowed") {
          wanted.current = false;
          setOn(false);
          setError("Microphone blocked. Allow it for this site and try again.");
        }
      };
      r.onend = () => {
        rec.current = null;
        // Android ends the session after every utterance whatever `continuous`
        // says, so "keep listening" means "start it again" — the single most
        // important line in this file. Without it the wake word works exactly
        // once per page load, which is worse than not having it.
        if (wanted.current) window.setTimeout(start, 250);
        else setListening(false);
      };
      try {
        r.start();
        rec.current = r;
        setListening(true);
        setError("");
      } catch {
        rec.current = null;
      }
    };

    const stop = () => {
      wanted.current = false;
      setListening(false);
      setAwake(false);
      const r = rec.current;
      rec.current = null;
      try { r?.abort(); } catch { /* already gone */ }
    };

    const decide = () => {
      const should = on && !speaking && document.visibilityState === "visible";
      if (should && !wanted.current) {
        wanted.current = true;
        start();
      } else if (!should && wanted.current) {
        stop();
      }
    };

    decide();
    document.addEventListener("visibilitychange", decide);
    return () => {
      document.removeEventListener("visibilitychange", decide);
      stop();
    };
  }, [on, speaking, handle]);

  // The awake window closes on its own, so the indicator has to as well.
  useEffect(() => {
    if (!awake) return;
    const timer = window.setTimeout(() => {
      if (Date.now() >= awakeUntil.current) setAwake(false);
    }, AWAKE_MS + 200);
    return () => window.clearTimeout(timer);
  }, [awake]);

  return { supported: supported(), listening, awake, error, on, setOn };
}
