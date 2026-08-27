/* Choosing the voice, by hearing it.
 *
 * "The male voice is robotic" is not something I can fix by guessing, because
 * which voices a phone has depends entirely on its text-to-speech engine. The
 * ranking underneath prefers the natural-sounding ones — Google's neural
 * voices, Microsoft's Natural, Apple's Enhanced — over the on-device ones,
 * which are the synthetic-sounding half. But a ranking is still a guess.
 *
 * So: the list, a preview on every row, and one tap to keep it. Ten seconds
 * settles what no amount of name-matching can.
 *
 * The device-level caveat is stated rather than left to be discovered. If the
 * phone's engine is Pico — still the default on some Androids — every voice it
 * offers is robotic and no choice here helps; installing Google's engine is the
 * fix, and being told that beats trying all six.
 */
import { useEffect, useState } from "react";

import * as speech from "../lib/speak";

const SAMPLE = "Good evening. Your exam is on the eighteenth, and I'll remind you the day before.";

export function VoicePicker() {
  const [list, setList] = useState<{ name: string; lang: string; good: boolean }[]>([]);
  const [chosen, setChosen] = useState(speech.chosenVoice);
  const [playing, setPlaying] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    speech.voices().then((v) => {
      if (!alive) return;
      setList(v);
      setLoaded(true);
    });
    return () => {
      alive = false;
    };
  }, []);

  async function preview(name: string) {
    speech.silence();
    setPlaying(name);
    speech.chooseVoice(name);
    setChosen(name);
    await speech.speak(SAMPLE);
    setPlaying("");
  }

  if (!loaded) return null;

  return (
    <section className="panel bracket">
      <span className="label">Voice</span>

      {list.length === 0 ? (
        <p className="muted small">
          This device has no speech voices installed. On Android: Settings →
          Accessibility → Text-to-speech.
        </p>
      ) : (
        <>
          <p className="muted small">
            Tap one to hear it. Whichever you pick is the one Jarvis uses.
          </p>
          <ul className="voices">
            {list.map((v) => (
              <li key={v.name}>
                <button
                  className={`voice-row${chosen === v.name ? " voice-on" : ""}`}
                  onClick={() => preview(v.name)}
                  disabled={playing === v.name}
                >
                  <span className="voice-name">{v.name}</span>
                  {v.good && <span className="chip chip-good voice-tag">NATURAL</span>}
                  <span className="voice-play label">
                    {playing === v.name ? "…" : chosen === v.name ? "USING" : "PLAY"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {chosen && (
            <button
              className="linkish label"
              onClick={() => {
                speech.chooseVoice("");
                setChosen("");
              }}
            >
              Use the best one automatically
            </button>
          )}
        </>
      )}

      <p className="muted small">
        If every voice here sounds robotic, the phone&rsquo;s speech engine is the
        cause rather than the choice. Install <span className="mono">Google
        Speech Services</span> and select it under Settings → Accessibility →
        Text-to-speech → Preferred engine.
      </p>
    </section>
  );
}
