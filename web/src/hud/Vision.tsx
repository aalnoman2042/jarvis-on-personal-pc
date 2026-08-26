/* The eye — the honest version of the movie's face-scan panel.
 *
 * You give it a picture, from the camera or a file, and Jarvis says what is in
 * it: reads the text, describes the scene, tells you what is wrong. It does not
 * identify people, because that needs a database of faces nobody has; it reads
 * what is in the frame, which is the part that is both real and useful.
 *
 * The image never leaves for anywhere but the core, and the core keeps only the
 * words, not the picture — so pointing it at a page of notes is not the same as
 * uploading the notes.
 *
 * `capture="environment"` on the file input is what makes a phone open the rear
 * camera straight to a shot rather than a gallery, so "show it something" is one
 * tap. A laptop with no camera falls back to picking a file, which is the same
 * code path.
 */
import { useRef, useState } from "react";

import { look } from "../lib/api";
import { shrink } from "../lib/image";

export function Vision({ token }: { token: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string>("");
  const [said, setSaid] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function chosen(file: File | undefined) {
    if (!file) return;
    setError("");
    setSaid("");
    setBusy(true);
    // A thumbnail so you can see what it is looking at while it looks.
    const url = URL.createObjectURL(file);
    setPreview((old) => {
      if (old) URL.revokeObjectURL(old);
      return url;
    });
    try {
      const small = await shrink(file);
      setSaid(await look(token, small));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't look at that.");
    }
    setBusy(false);
  }

  return (
    <section className="panel bracket panel-wide vision">
      <div className="vision-top">
        <span className="label">Vision</span>
        <span className="chip chip-quiet">GEMINI</span>
      </div>

      <div className="vision-body">
        <button
          type="button"
          className="vision-frame"
          onClick={() => input.current?.click()}
          disabled={busy}
          aria-label="Show Jarvis something"
        >
          {preview ? (
            <img src={preview} alt="" className="vision-shot" />
          ) : (
            <span className="vision-hint">
              <span className="vision-glyph" aria-hidden>⊹</span>
              Point the camera, or pick an image
            </span>
          )}
          {busy && <span className="vision-scan" aria-hidden />}
        </button>

        <div className="vision-read">
          {error && <p className="mic-error label">{error}</p>}
          {said ? (
            <p className="vision-said">{said}</p>
          ) : (
            <p className="muted small">
              Show it a document, a screen, an error message, a room. It reads
              the text and tells you what is there — it does not identify people.
            </p>
          )}
        </div>
      </div>

      <input
        ref={input}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(e) => chosen(e.target.files?.[0])}
      />
    </section>
  );
}
