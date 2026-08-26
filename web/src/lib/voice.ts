/* Listening.
 *
 * Records a few seconds from the microphone, sends it to the cloud core, and
 * hands back the words. Recording here rather than using the browser's own
 * recogniser is deliberate: `SpeechRecognition` is a Chrome feature, and the
 * Android WebView the app runs in usually does not have it. A microphone that
 * works in the browser and not in the app would be worse than one that behaves
 * the same everywhere, so both go the same way.
 *
 * **It stops listening by itself.** Holding a button down while you talk is
 * fiddly on a phone — a stray scroll cancels it — and tapping twice means
 * remembering to. So a tap starts it, and it ends when you stop talking. The
 * level meter that decides that is the same number the reactor pulses to, which
 * is what makes it obvious it is hearing you.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { transcribe } from "./api";
import { apiBase } from "./endpoint";

/** Below this, that is room tone rather than a voice. */
const SILENCE = 0.045;
/** Quiet for this long, after something was said, means finished. */
const HANG_MS = 1400;
/** Nobody dictates an essay at a HUD, and Whisper charges by the second. */
const MAX_MS = 20000;
/** Give up waiting for a first word rather than uploading ten seconds of room. */
const NOTHING_SAID_MS = 6000;

function pickMime(): string {
  const options = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ];
  for (const type of options) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(type)) return type;
  }
  return "";
}

export interface Voice {
  supported: boolean;
  listening: boolean;
  working: boolean;
  /** 0–1, for the reactor and the button. */
  level: number;
  error: string;
  toggle: () => void;
  stop: () => void;
}

export function useVoice(token: string, onHeard: (text: string) => void): Voice {
  const [listening, setListening] = useState(false);
  const [working, setWorking] = useState(false);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState("");

  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const audio = useRef<AudioContext | null>(null);
  const frame = useRef<number | null>(null);
  const timers = useRef<number[]>([]);
  // Read inside the animation loop, which runs outside React and must not close
  // over a stale render's value.
  const heardSomething = useRef(false);

  const teardown = useCallback(() => {
    timers.current.forEach((t) => window.clearTimeout(t));
    timers.current = [];
    if (frame.current) cancelAnimationFrame(frame.current);
    frame.current = null;
    audio.current?.close().catch(() => {});
    audio.current = null;
    // Releasing the tracks is what turns off the recording indicator. Leaving
    // them open leaves a phone saying an app is listening when it is not.
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    recorder.current = null;
    setLevel(0);
    setListening(false);
  }, []);

  const stop = useCallback(() => {
    if (recorder.current && recorder.current.state !== "inactive") {
      recorder.current.stop(); // teardown happens in onstop, after the last chunk
    } else {
      teardown();
    }
  }, [teardown]);

  const start = useCallback(async () => {
    setError("");
    heardSomething.current = false;

    // Wake the free tier the instant the mic opens, not when the clip is ready.
    // A Render cold start is the better part of a minute; the few seconds spent
    // talking is a head start on it, so by the time there is a clip to send the
    // server is far more likely to be up. Fire-and-forget — the transcribe call
    // has its own retry if this was not enough.
    fetch(apiBase() + "/health").catch(() => {});

    try {
      const media = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      stream.current = media;

      const mime = pickMime();
      const rec = new MediaRecorder(media, mime ? { mimeType: mime } : undefined);
      recorder.current = rec;
      const chunks: BlobPart[] = [];
      rec.ondataavailable = (e) => {
        if (e.data.size) chunks.push(e.data);
      };
      rec.onstop = async () => {
        const spoke = heardSomething.current;
        teardown();
        if (!spoke || !chunks.length) return;
        setWorking(true);
        try {
          const said = await transcribe(token, new Blob(chunks, { type: mime || "audio/webm" }));
          if (said) onHeard(said);
          else setError("I didn't catch that.");
        } catch (err) {
          setError(err instanceof Error ? err.message : "Couldn't reach the core.");
        }
        setWorking(false);
      };
      rec.start();
      setListening(true);

      // The meter. One AudioContext, one rAF loop, torn down with everything
      // else — the same rule the reactor keeps.
      const ctx = new AudioContext();
      audio.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      ctx.createMediaStreamSource(media).connect(analyser);
      const buffer = new Float32Array(analyser.fftSize);
      let quietSince = 0;

      const tick = () => {
        analyser.getFloatTimeDomainData(buffer);
        let sum = 0;
        for (let i = 0; i < buffer.length; i += 1) sum += buffer[i] * buffer[i];
        const rms = Math.sqrt(sum / buffer.length);
        setLevel(Math.min(1, rms * 8));

        const now = performance.now();
        if (rms > SILENCE) {
          heardSomething.current = true;
          quietSince = 0;
        } else if (heardSomething.current) {
          if (!quietSince) quietSince = now;
          else if (now - quietSince > HANG_MS) {
            stop();
            return;
          }
        }
        frame.current = requestAnimationFrame(tick);
      };
      frame.current = requestAnimationFrame(tick);

      timers.current.push(window.setTimeout(stop, MAX_MS));
      timers.current.push(
        window.setTimeout(() => {
          if (!heardSomething.current) stop();
        }, NOTHING_SAID_MS),
      );
    } catch (err) {
      teardown();
      // The message matters here: "denied" and "no microphone" need different
      // things from the person reading it.
      const name = (err as { name?: string })?.name || "";
      if (name === "NotAllowedError") setError("Microphone permission is off.");
      else if (name === "NotFoundError") setError("No microphone on this device.");
      else setError("Couldn't start the microphone.");
    }
  }, [token, onHeard, stop, teardown]);

  const toggle = useCallback(() => {
    if (listening) stop();
    else start();
  }, [listening, start, stop]);

  useEffect(() => teardown, [teardown]);

  return {
    supported: typeof navigator !== "undefined"
      && !!navigator.mediaDevices?.getUserMedia
      && typeof MediaRecorder !== "undefined",
    listening,
    working,
    level,
    error,
    toggle,
    stop,
  };
}
