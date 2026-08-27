/* "Read it aloud", and the honest answer when it cannot.
 *
 * Lifted out of Brief so the weekly report gets the same behaviour rather than
 * a second copy of it. The fallback message is the part worth sharing: a button
 * that does nothing and says nothing is worse than no button, and the two
 * reasons a device cannot speak have completely different fixes — an APK with
 * no speech engine needs a reinstall, a browser with no installed voice needs a
 * trip to Android's accessibility settings. Telling someone the wrong one costs
 * them an evening.
 *
 * The message goes back to the caller rather than being rendered here, because
 * it belongs under the text and this button lives in a row of controls.
 */
import * as speech from "../lib/speak";

export function whyItCannotSpeak(): string {
  const inApp = Boolean(
    (window as unknown as {
      Capacitor?: { isNativePlatform?: () => boolean };
    }).Capacitor?.isNativePlatform?.(),
  );
  return inApp
    ? "This app build cannot speak — Android's WebView has no speech engine of "
      + "its own. Install the newest APK; screens update themselves, this part "
      + "cannot."
    : "No speech voice on this device. Android: Settings → Accessibility → "
      + "Text-to-speech.";
}

export function SpeakButton({ text, onNote, label = "Read it" }: {
  text: string;
  /** Called with an explanation when the device turns out to have no voice,
      and with "" when a reading starts, so a stale complaint clears. */
  onNote: (note: string) => void;
  label?: string;
}) {
  if (!speech.available()) return null;

  return (
    <button
      className="linkish label"
      onClick={async () => {
        onNote("");
        const spoke = await speech.speak(text);
        if (!spoke) onNote(whyItCannotSpeak());
      }}
    >
      {label}
    </button>
  );
}
