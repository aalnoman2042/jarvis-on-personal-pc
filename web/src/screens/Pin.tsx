/* The way in.
 *
 * Four digits on a keypad. A real keypad rather than a text field because this
 * is mostly used one-handed on a phone, and a numeric input still invites the
 * full keyboard on some Android builds.
 *
 * The PIN is typed once per device: a correct one is exchanged for a long-lived
 * token that the HUD keeps, so it never travels again.
 */
import { useCallback, useEffect, useState } from "react";

import { login } from "../lib/api";
import { deviceName } from "../lib/store";

const LENGTH = 4;
const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "del"];

export function Pin({ onIn }: { onIn: (token: string) => void }) {
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [shake, setShake] = useState(false);

  const submit = useCallback(
    async (value: string) => {
      setBusy(true);
      setError("");
      try {
        const result = await login(value, deviceName());
        onIn(result.token);
      } catch (err) {
        setError(err instanceof Error ? err.message : "That didn't work.");
        setPin("");
        setShake(true);
        setBusy(false);
        window.setTimeout(() => setShake(false), 420);
      }
    },
    [onIn],
  );

  // Submit on the fourth digit rather than making you reach for a button.
  useEffect(() => {
    if (pin.length === LENGTH && !busy) submit(pin);
  }, [pin, busy, submit]);

  const press = useCallback(
    (key: string) => {
      if (busy) return;
      setError("");
      if (key === "del") setPin((p) => p.slice(0, -1));
      else if (key && pin.length < LENGTH) setPin((p) => p + key);
    },
    [busy, pin.length],
  );

  // A physical keyboard should work too — this is a desktop app as well.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (/^[0-9]$/.test(e.key)) press(e.key);
      else if (e.key === "Backspace") press("del");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [press]);

  return (
    <div className="pair">
      <div className={`pin-card bracket${shake ? " pin-shake" : ""}`}>
        <span className="label">Jarvis</span>
        <h1>Enter your PIN</h1>

        <div className="pin-dots" role="status" aria-label={`${pin.length} of ${LENGTH} digits entered`}>
          {Array.from({ length: LENGTH }, (_, i) => (
            <span key={i} className={`pin-dot${i < pin.length ? " pin-dot-on" : ""}`} />
          ))}
        </div>

        <p className={`pin-msg${error ? " pin-msg-bad" : ""}`}>
          {busy ? "Checking…" : error || " "}
        </p>

        <div className="pin-pad">
          {KEYS.map((key, i) =>
            key === "" ? (
              <span key={i} />
            ) : (
              <button
                key={i}
                className={`pin-key${key === "del" ? " pin-key-del" : ""}`}
                onClick={() => press(key)}
                disabled={busy}
                aria-label={key === "del" ? "Delete" : key}
              >
                {key === "del" ? "⌫" : key}
              </button>
            ),
          )}
        </div>
      </div>
    </div>
  );
}
