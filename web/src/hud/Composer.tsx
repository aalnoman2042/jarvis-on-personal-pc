/* Where you type. The microphone button lands here in phase 06.
 *
 * Enter sends, Shift+Enter breaks a line. The field never disables itself while
 * Jarvis is thinking — you should be able to start the next sentence without
 * waiting, the same as talking to a person.
 *
 * It grows with what you write, up to a few lines. A fixed one-line box on a
 * phone means a long message scrolls away inside a slot too small to read it
 * back, and you send something you cannot see.
 */
import { useEffect, useRef, useState } from "react";

import { Mic } from "./Mic";
import { look } from "../lib/api";
import { shrink } from "../lib/image";
import type { Voice } from "../lib/voice";

const MAX_ROWS_PX = 120;

export function Composer({ onSay, busy, voice, token, onShow }: {
  onSay: (text: string) => void;
  busy: boolean;
  voice?: Voice;
  /** Both needed to send a picture; omit them and the attach button hides. */
  token?: string;
  onShow?: (image: string, said: string, question?: string) => void;
}) {
  const [text, setText] = useState("");
  const [looking, setLooking] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);

  // Height is measured, not guessed: reset to nothing, read what the content
  // needs, then set it. Doing it in an effect keeps it right after a send
  // clears the box as well as while typing.
  useEffect(() => {
    const el = field.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_ROWS_PX)}px`;
  }, [text]);

  function send() {
    const value = text.trim();
    if (!value) return;
    onSay(value);
    setText("");
    field.current?.focus();
  }

  /** A picture goes into the conversation with whatever was typed as the
      question — "what does this say?" alongside the photo, the way you would
      hand something to a person. */
  async function attach(file: File | undefined) {
    if (!file || !token || !onShow) return;
    const question = text.trim();
    setText("");
    setLooking(true);
    // Kept as an object URL: the picture stays in this tab and never reaches
    // the database. Only what Jarvis saw in it is remembered.
    const preview = URL.createObjectURL(file);
    try {
      const said = await look(token, await shrink(file), question);
      onShow(preview, said, question);
    } catch (err) {
      onShow(preview, err instanceof Error ? err.message : "I couldn't look at that.",
             question);
    }
    setLooking(false);
    if (picker.current) picker.current.value = "";
  }

  return (
    <form
      className="composer bracket"
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      <textarea
        ref={field}
        rows={1}
        value={text}
        placeholder={
          looking
            ? "Looking at that…"
            : voice?.listening
            ? "Listening…"
            : voice?.working
              ? "Working out what you said…"
              : busy
                ? "Jarvis is thinking…"
                : "Say something to Jarvis"
        }
        onChange={(e) => setText(e.target.value)}
        onFocus={() => {
          // Android raises the keyboard a beat after focus. Nudging the field
          // into view once it has settled covers the browsers that do not do it
          // themselves, and costs nothing on the ones that do.
          window.setTimeout(() => field.current?.scrollIntoView({ block: "end" }), 250);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
        aria-label="Message to Jarvis"
      />
      {token && onShow && (
        <>
          <button
            type="button"
            className="attach"
            onClick={() => picker.current?.click()}
            disabled={looking}
            aria-label="Show Jarvis a picture"
            title="Show Jarvis a picture"
          >
            <span aria-hidden>{looking ? "···" : "⊹"}</span>
          </button>
          <input
            ref={picker}
            type="file"
            accept="image/*"
            hidden
            onChange={(e) => attach(e.target.files?.[0])}
          />
        </>
      )}
      {voice && <Mic voice={voice} />}
      <button type="submit" className="send" disabled={!text.trim()} aria-label="Send">
        <span aria-hidden>&#9654;</span>
      </button>
    </form>
  );
}
