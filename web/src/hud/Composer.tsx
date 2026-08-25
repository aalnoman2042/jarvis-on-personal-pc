/* Where you type. The microphone button lands here in phase 06.
 *
 * Enter sends, Shift+Enter breaks a line. The field never disables itself while
 * Jarvis is thinking — you should be able to start the next sentence without
 * waiting, the same as talking to a person.
 */
import { useRef, useState } from "react";

export function Composer({ onSay, busy }: { onSay: (text: string) => void; busy: boolean }) {
  const [text, setText] = useState("");
  const field = useRef<HTMLTextAreaElement>(null);

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
