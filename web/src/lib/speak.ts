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

/* Measured rather than brisk. 1.05 was a shade quick for a voice you listen to
   with the screen away, and a briefing read fast is a briefing you re-read. */
const RATE = 0.88;
const PITCH = 0.92;

/* Picking a male voice, which is a surprisingly awkward thing to ask a device.
 *
 * There is no gender field on a voice — only a name — so this is name matching,
 * and the first trap is that "female" CONTAINS "male". Anything checking for
 * "male" naively selects exactly the wrong half of the list.
 *
 * After that it is a list of the names Android, Windows and iOS actually ship.
 * A miss is not a failure: no match simply leaves the platform default, which
 * is better than refusing to speak because the preferred voice is absent. */
const MALE_NAMES = new RegExp(
  "\\b(david|daniel|alex|fred|george|james|mark|thomas|oliver|arthur|"
  + "aaron|eddy|reed|rishi|ravi|hemant|prabhat|guy|christopher|roger|steffan|"
  + "liam|jorge|diego|male)\\b",
  "i",
);

function soundsMale(name: string): boolean {
  const n = (name || "").toLowerCase();
  if (/\bfemale\b/.test(n)) return false;  // "female" contains "male"
  return MALE_NAMES.test(n);
}

/* Android's WebView does not implement the Web Speech API's synthesis half.
 *
 * `window.speechSynthesis` is present — which is why the Read It button
 * appeared and why `available()` said yes — but `getVoices()` returns an empty
 * list for ever and `speak()` makes no sound at all. It is a Chrome feature,
 * not a WebView one, so it worked on the desktop and was silent in the app, and
 * waiting longer for voices could never have helped because none were coming.
 *
 * So the app uses the platform's own text-to-speech through a plugin, and the
 * browser keeps the Web Speech path. Same two-roads shape as listening: the
 * WebView cannot be relied on for either half of the Web Speech API. */
type NativeTts = typeof import("@capacitor-community/text-to-speech").TextToSpeech;

function nativePlatform(): boolean {
  const cap = (window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor;
  return Boolean(cap?.isNativePlatform?.());
}

let nativeTts: NativeTts | null | undefined;

async function native(): Promise<NativeTts | null> {
  if (nativeTts !== undefined) return nativeTts;
  if (!nativePlatform()) {
    nativeTts = null;
    return null;
  }
  try {
    const mod = await import("@capacitor-community/text-to-speech");
    nativeTts = mod.TextToSpeech;
  } catch {
    // An APK built before the plugin existed. The button will say so rather
    // than failing mutely, which is what it did before.
    nativeTts = null;
  }
  return nativeTts;
}

function nativeShell(): boolean {
  const cap = (window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor;
  return Boolean(cap?.isNativePlatform?.());
}

export function available(): boolean {
  if (typeof window === "undefined") return false;
  // In the app the plugin is what speaks; in a browser it is the Web Speech
  // API. Either counts, and the button is offered on that basis.
  return nativePlatform() || "speechSynthesis" in window;
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

/** The best English voice this device has: male if it has one, local if it can. */
function pickFrom(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  if (!voices.length) return null;
  const english = voices.filter((v) => v.lang.toLowerCase().startsWith("en"));
  const pool = english.length ? english : voices;
  const male = pool.filter((v) => soundsMale(v.name));
  const wanted = male.length ? male : pool;
  // A local voice does not need the network and does not stall on a bad
  // connection, which is exactly when you are most likely to be listening
  // rather than reading.
  return wanted.find((v) => v.localService) || wanted[0];
}

/** The index of a male English voice in the plugin's list, or -1 for default. */
let nativeVoiceIndex: number | undefined;

async function nativeVoice(tts: NativeTts): Promise<number> {
  if (nativeVoiceIndex !== undefined) return nativeVoiceIndex;
  nativeVoiceIndex = -1;
  try {
    const list = (await tts.getSupportedVoices()).voices || [];
    const english = list
      .map((v, i) => ({ v, i }))
      .filter(({ v }) => (v.lang || "").toLowerCase().startsWith("en"));
    const male = english.find(({ v }) => soundsMale(v.name || ""));
    if (male) nativeVoiceIndex = male.i;
  } catch {
    /* the platform default is a perfectly good answer */
  }
  return nativeVoiceIndex;
}

export async function speak(text: string): Promise<boolean> {
  if (!available() || !enabled()) return false;
  const words = (text || "").trim();
  if (!words) return false;

  const tts = await native();
  if (tts) {
    try {
      await tts.stop();          // never two voices at once
      const chosen = await nativeVoice(tts);
      await tts.speak({
        text: words,
        lang: "en-US",
        rate: RATE,
        pitch: PITCH,
        volume: 1.0,
        category: "playback",
        ...(chosen >= 0 ? { voice: chosen } : {}),
      });
      return true;
    } catch {
      return false;
    }
  }
  if (nativePlatform()) {
    // In the app with no plugin: nothing can speak, and pretending otherwise is
    // how this went unnoticed for so long.
    return false;
  }

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
  utterance.rate = RATE;
  utterance.pitch = PITCH;

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
  native().then((tts) => tts?.stop().catch(() => {}));
  if (typeof window !== "undefined" && "speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
}
