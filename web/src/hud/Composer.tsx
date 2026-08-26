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

const MAX_ROWS_PX = 120;

export function Composer({ onSay, busy }: { onSay: (text: string) => void; busy: boolean }) {
  const [text, setText] = useState("");
  const field = useRef<HTMLTextAreaElement>(null);

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
        placeholder={busy ? "Jarvis is thinking…" : "Say something to Jarvis"}
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
      <button type="submit" className="send" disabled={!text.trim()} aria-label="Send">
        <span aria-hidden>&#9654;</span>
      </button>
    </form>
  );
}
