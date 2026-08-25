/* Getting this device authorised.
 *
 * Two doors, and the screen decides which to show rather than asking Rohan to
 * understand the difference:
 *
 *   * If the server has no devices yet, this is the first one, and it wants the
 *     server's pairing secret. That door closes permanently the moment it works.
 *   * Otherwise a device is already paired, so this one needs a six-digit code
 *     read off it.
 */
import { useEffect, useState } from "react";

import { bootstrap, claim, health } from "../lib/api";
import { deviceName } from "../lib/store";

type Mode = "checking" | "first" | "code";

export function Pair({ onPaired }: { onPaired: (token: string) => void }) {
  const [mode, setMode] = useState<Mode>("checking");
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    health()
      .then((info) => alive && setMode(info.devices_paired ? "code" : "first"))
      // If the check itself fails the server may simply be starting. Asking for
      // a code is the safe guess: it fails politely, where offering the
      // first-device door on an already-set-up server would be misleading.
      .catch(() => alive && setMode("code"));
    return () => {
      alive = false;
    };
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const entry = value.trim();
    if (!entry || busy) return;
    setBusy(true);
    setError("");
    try {
      const result =
        mode === "first"
          ? await bootstrap(entry, deviceName())
          : await claim(entry, deviceName());
      onPaired(result.token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "That didn't work.");
      setBusy(false);
    }
  }

  if (mode === "checking") {
    return (
      <div className="pair">
        <p className="label">Looking for Jarvis…</p>
      </div>
    );
  }

  const first = mode === "first";

  return (
    <div className="pair">
      <form className="pair-card bracket" onSubmit={submit}>
        <span className="label">{first ? "First device" : "Pair this device"}</span>
        <h1>{first ? "Claim your Jarvis" : "Enter the code"}</h1>
        <p className="pair-help">
          {first
            ? "Nothing is paired yet, so this device gets to be first. Type the pairing secret from your server's settings."
            : "On a device that's already paired, ask Jarvis to pair a new device. It'll give you a six-digit code."}
        </p>

        <input
          className="mono pair-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={first ? "pairing secret" : "000000"}
          type={first ? "password" : "text"}
          inputMode={first ? "text" : "numeric"}
          maxLength={first ? 200 : 6}
          autoFocus
          aria-label={first ? "Pairing secret" : "Six-digit code"}
        />

        {error && <p className="pair-error">{error}</p>}

        <button className="pair-go" type="submit" disabled={busy || !value.trim()}>
          {busy ? "Checking…" : first ? "Claim it" : "Pair"}
        </button>

        <p className="pair-foot label">
          {first
            ? "This works only while no device is paired."
            : "Codes last five minutes and work once."}
        </p>
      </form>
    </div>
  );
}
