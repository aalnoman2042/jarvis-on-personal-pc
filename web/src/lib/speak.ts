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

/** The most natural English voice this device has, preferring a local one. */
function pickVoice(): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices();
  if (!voices.length) return null; // Chrome populates these asynchronously
  const english = voices.filter((v) => v.lang.toLowerCase().startsWith("en"));
  const pool = english.length ? english : voices;
  // A local voice does not need the network and does not stall on a bad
  // connection, which is exactly when you are most likely to be listening
  // rather than reading.
  return pool.find((v) => v.localService) || pool[0];
}

export function speak(text: string): void {
  if (!available() || !enabled()) return;
  const words = (text || "").trim();
  if (!words) return;

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(words);
  const voice = pickVoice();
  if (voice) {
    utterance.voice = voice;
    utterance.lang = voice.lang;
  }
  // Slightly quick and slightly low. Jarvis is composed, not chirpy, and the
  // default rate reads long answers at a pace that invites skipping.
  utterance.rate = 1.05;
  utterance.pitch = 0.95;
  try {
    window.speechSynthesis.speak(utterance);
  } catch {
    /* a voice that refuses to load is not worth an error on screen */
  }
}

export function silence(): void {
  if (available()) window.speechSynthesis.cancel();
}
