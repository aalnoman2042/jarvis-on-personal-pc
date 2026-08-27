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

/* Pitch is left ALONE, and that is the single biggest thing for smoothness.
 *
 * Most engines implement a pitch change as a resample after synthesis rather
 * than by synthesising differently — so shifting it away from 1.0 degrades the
 * voice and adds precisely the metallic edge it was meant to remove. 0.92 was
 * making the voice more robotic, not less. A neural voice at its own pitch
 * sounds like a person; the same voice shifted sounds like a machine trying to.
 *
 * Rate is a genuine control and is left adjustable — see `rate()`. The default
 * is gently under natural: slow enough to follow with the screen away, not so
 * slow that it drags, which is its own kind of unnatural. */
const PITCH = 1.0;
const DEFAULT_RATE = 0.94;
const RATE_KEY = "vondo.rate";
const VOICE_KEY = "vondo.voice";

/** How fast it reads, 0.6 to 1.3. Kept per device like the mute toggle. */
export function rate(): number {
  try {
    const saved = Number(localStorage.getItem(RATE_KEY));
    if (saved >= 0.6 && saved <= 1.3) return saved;
  } catch {
    /* fall through to the default */
  }
  return DEFAULT_RATE;
}

export function setRate(value: number): void {
  const clamped = Math.max(0.6, Math.min(1.3, value));
  try {
    localStorage.setItem(RATE_KEY, String(clamped));
  } catch {
    /* the setting simply does not persist */
  }
}

/* Which voices actually sound like a person.
 *
 * The first version preferred LOCAL voices, on the reasoning that they do not
 * need the network. That is true and it is exactly backwards for quality: the
 * on-device voices are the robotic ones, and the natural-sounding ones are
 * network-backed neural models. A voice that stalls occasionally beats one that
 * sounds like a railway announcement every time.
 *
 * Android is the hard case. If the phone's engine is Pico TTS — still the
 * default on some devices — everything it offers sounds synthetic and no amount
 * of picking helps; the fix is installing Google's engine, which is why the
 * picker says so rather than leaving you to wonder. */
const GOOD_VOICE = /(natural|neural|wavenet|studio|enhanced|premium|online|google)/i;
const POOR_VOICE = /(espeak|pico|compact|monotone)/i;

function quality(name: string): number {
  const n = (name || "").toLowerCase();
  if (POOR_VOICE.test(n)) return -2;
  if (GOOD_VOICE.test(n)) return 2;
  return 0;
}

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
  // Only a NON-EMPTY answer is cached, and that distinction is the whole bug.
  // Chrome on Android reports no voices until its engine has initialised, so
  // the first call resolves empty — and caching that meant the list stayed
  // empty for the rest of the session no matter how long the engine took. The
  // picker showed nothing on a phone and everything on a desktop for exactly
  // this reason.
  if (voicesReady) return voicesReady;

  voicesReady = new Promise((resolve) => {
    const now = window.speechSynthesis.getVoices();
    if (now.length) {
      resolve(now);
      return;
    }
    let settled = false;
    let waited = 0;
    const done = (list: SpeechSynthesisVoice[]) => {
      if (settled) return;
      settled = true;
      window.speechSynthesis.removeEventListener("voiceschanged", heard);
      window.clearInterval(timer);
      // An empty result is not worth keeping: let the next caller try again,
      // by which time the engine may well be up.
      if (!list.length) voicesReady = null;
      resolve(list);
    };
    const heard = () => done(window.speechSynthesis.getVoices());
    window.speechSynthesis.addEventListener("voiceschanged", heard);

    // Polled as well as listened for. Several engines populate the list
    // without ever firing the event, which is not something to discover from a
    // silent button.
    const timer = window.setInterval(() => {
      waited += 250;
      const list = window.speechSynthesis.getVoices();
      if (list.length || waited >= 4000) done(list);
    }, 250);
  });
  return voicesReady;
}

/** Forget the cached list, so the next read asks the engine again. */
export function forgetVoices(): void {
  voicesReady = null;
}

/** The best English voice this device has, or the one that was chosen by hand. */
function pickFrom(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  if (!voices.length) return null;
  const saved = savedVoice();
  if (saved) {
    const exact = voices.find((v) => v.name === saved);
    if (exact) return exact;      // a choice outranks any ranking
  }
  const english = voices.filter((v) => v.lang.toLowerCase().startsWith("en"));
  const pool = english.length ? english : voices;
  // Sounding human first, male second. A robotic male voice is a worse answer
  // to "I prefer male" than a natural one of either kind, and quality is the
  // thing people actually notice.
  const ranked = [...pool].sort((a, b) =>
    (quality(b.name) - quality(a.name))
    || (Number(soundsMale(b.name)) - Number(soundsMale(a.name))));
  return ranked[0] || null;
}

function savedVoice(): string {
  try {
    return localStorage.getItem(VOICE_KEY) || "";
  } catch {
    return "";
  }
}

/** Every voice that could read to you here, best first. */
export async function voices(): Promise<{ name: string; lang: string; good: boolean }[]> {
  const tts = await native();
  if (tts) {
    try {
      const list = (await tts.getSupportedVoices()).voices || [];
      return list
        .filter((v) => (v.lang || "").toLowerCase().startsWith("en"))
        .map((v) => ({ name: v.name || "", lang: v.lang || "", good: quality(v.name || "") > 0 }))
        .sort((a, b) => Number(b.good) - Number(a.good));
    } catch {
      return [];
    }
  }
  if (!("speechSynthesis" in window)) return [];
  const list = await loadVoices();
  return list
    .filter((v) => v.lang.toLowerCase().startsWith("en"))
    .map((v) => ({ name: v.name, lang: v.lang, good: quality(v.name) > 0 }))
    .sort((a, b) => Number(b.good) - Number(a.good));
}

export function chosenVoice(): string {
  return savedVoice();
}

export function chooseVoice(name: string): void {
  try {
    if (name) localStorage.setItem(VOICE_KEY, name);
    else localStorage.removeItem(VOICE_KEY);
  } catch {
    /* the choice simply does not persist */
  }
  nativeVoiceIndex = undefined;   // re-resolve against the new preference
}

/** The index of a male English voice in the plugin's list, or -1 for default. */
let nativeVoiceIndex: number | undefined;

async function nativeVoice(tts: NativeTts): Promise<number> {
  if (nativeVoiceIndex !== undefined) return nativeVoiceIndex;
  nativeVoiceIndex = -1;
  try {
    const list = (await tts.getSupportedVoices()).voices || [];
    const saved = savedVoice();
    if (saved) {
      const exact = list.findIndex((v) => (v.name || "") === saved);
      if (exact >= 0) {
        nativeVoiceIndex = exact;
        return nativeVoiceIndex;
      }
    }
    const english = list
      .map((v, i) => ({ v, i }))
      .filter(({ v }) => (v.lang || "").toLowerCase().startsWith("en"));
    // Sounding human first, male second — see pickFrom.
    english.sort((a, b) =>
      (quality(b.v.name || "") - quality(a.v.name || ""))
      || (Number(soundsMale(b.v.name || "")) - Number(soundsMale(a.v.name || ""))));
    if (english.length) nativeVoiceIndex = english[0].i;
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
        rate: rate(),
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
  utterance.rate = rate();
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
