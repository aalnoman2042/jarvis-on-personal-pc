/* Speaking.
 *
 * `speechSynthesis` is the one half of the Web Speech API that the Android
 * WebView does reliably have, so unlike listening this needs no server and no
 * key — it is free, offline, and instant.
 *
 * Two rules it keeps:
 *
 * **Only one voice at a time.** A reply arriving while the last one is still
 * being read cancels it. Two overlapping voices are unintelligible, and the new
 * answer is always the one you want.
 *
 * **Off is remembered.** Somebody who mutes Jarvis on a bus does not want to
 * mute it again at the next stop, so the choice is kept per device. It starts
 * ON in the app and OFF in a browser tab: a phone you are talking to should
 * talk back, and a tab you opened on a laptop at 2am should not.
 */
const KEY = "vondo.speak";

function nativeShell(): boolean {
  const cap = (window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor;
  return Boolean(cap?.isNativePlatform?.());
}

export function available(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function enabled(): boolean {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved !== null) return saved === "1";
  } catch {
    /* private mode, or storage refused; fall through to the default */
  }
  return nativeShell();
}

export function setEnabled(on: boolean): void {
  try {
    localStorage.setItem(KEY, on ? "1" : "0");
  } catch {
    /* the setting simply does not persist; speaking still works this session */
  }
  if (!on) silence();
}

/* Android loads its voice list asynchronously and reports an empty one until
 * the TTS engine is up — and asking it to speak before then does nothing at
 * all, silently. On a desktop the list is already warm by the time anyone
 * presses anything, which is exactly why this worked on the laptop and not on
 * the phone.
 *
 * So the list is awaited once, with a ceiling: a device with no voices at all
 * must not leave the button hanging for ever. */
let voicesReady: Promise<SpeechSynthesisVoice[]> | null = null;

function loadVoices(): Promise<SpeechSynthesisVoice[]> {
  if (voicesReady) return voicesReady;
  voicesReady = new Promise((resolve) => {
    const now = window.speechSynthesis.getVoices();
    if (now.length) {
      resolve(now);
      return;
    }
    let settled = false;
    const done = () => {
      if (settled) return;
      settled = true;
      window.speechSynthesis.removeEventListener("voiceschanged", done);
      resolve(window.speechSynthesis.getVoices());
    };
    window.speechSynthesis.addEventListener("voiceschanged", done);
    // Some engines never fire the event; speaking with no chosen voice still
    // works, so a timeout is a usable answer rather than a failure.
    window.setTimeout(done, 2000);
  });
  return voicesReady;
}

/** The most natural English voice this device has, preferring a local one. */
function pickFrom(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  if (!voices.length) return null;
  const english = voices.filter((v) => v.lang.toLowerCase().startsWith("en"));
  const pool = english.length ? english : voices;
  // A local voice does not need the network and does not stall on a bad
  // connection, which is exactly when you are most likely to be listening
  // rather than reading.
  return pool.find((v) => v.localService) || pool[0];
}

export async function speak(text: string): Promise<boolean> {
  if (!available() || !enabled()) return false;
  const words = (text || "").trim();
  if (!words) return false;

  const voices = await loadVoices();

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(words);
  const voice = pickFrom(voices);
  if (voice) {
    utterance.voice = voice;
    utterance.lang = voice.lang;
  } else {
    // No list at all: still speak, and let the engine pick. Refusing here is
    // how a working device ends up silent because it was slow to enumerate.
    utterance.lang = "en-US";
  }
  // Slightly quick and slightly low. Jarvis is composed, not chirpy, and the
  // default rate reads long answers at a pace that invites skipping.
  utterance.rate = 1.05;
  utterance.pitch = 0.95;

  // Did it actually start? `speak()` returning is not evidence of anything —
  // the WebView accepts the utterance and may never make a sound, which is the
  // failure that looked like "read-out is not available on the phone".
  return new Promise<boolean>((resolve) => {
    let started = false;
    utterance.onstart = () => {
      started = true;
      resolve(true);
    };
    utterance.onerror = () => resolve(false);
    try {
      window.speechSynthesis.speak(utterance);
    } catch {
      resolve(false);
      return;
    }
    window.setTimeout(() => {
      if (!started) resolve(false);
    }, 1500);
  });
}

export function silence(): void {
  if (available()) window.speechSynthesis.cancel();
}
