/* Getting your data out, and putting it back.
 *
 * Everything Jarvis knows lived in one hosted database with no export and no
 * second copy anywhere — every conversation, the diary, and now everybody's
 * phone number. A lapsed free tier, a lost login or a bad afternoon and a
 * year of someone's life would be gone with no way back.
 *
 * Plain JSON, so it is readable in ten years by something that is not this
 * program, and readable by Rohan — he should be able to open the file and see
 * his own sentences rather than a binary blob.
 *
 * Restore MERGES and never deletes. A restore that wipes the present to
 * recover the past is a worse accident than the one it is fixing.
 */
import { useEffect, useRef, useState } from "react";

import { backupSummary, downloadBackup, restoreBackup } from "../lib/api";

function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} kB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function Backup({ token }: { token: string }) {
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  useEffect(() => {
    backupSummary(token).then(setCounts).catch(() => {});
  }, [token]);

  async function save() {
    setBusy(true);
    setSaid("");
    try {
      const size = await downloadBackup(token);
      setSaid(`Saved — ${bytes(size)}. Keep it somewhere that isn't this phone.`);
    } catch {
      setSaid("Couldn't build the backup just now.");
    }
    setBusy(false);
  }

  async function load(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setSaid("");
    try {
      const payload = JSON.parse(await file.text());
      const { total } = await restoreBackup(token, payload);
      setSaid(total
        ? `Restored ${total} item${total === 1 ? "" : "s"}. Nothing was deleted.`
        : "Everything in that file was already here — nothing to add.");
      setCounts(await backupSummary(token));
    } catch {
      setSaid("That file could not be read as a Jarvis backup.");
    }
    setBusy(false);
    if (picker.current) picker.current.value = "";
  }

  const total = counts
    ? Object.values(counts).reduce((a, b) => a + b, 0)
    : 0;

  return (
    <section className="panel bracket">
      <span className="label">Your data</span>
      <h3 className="panel-head">{total || "—"}</h3>
      <p className="muted small">
        things remembered, in one hosted database. There is no other copy unless
        you make one.
      </p>

      {counts && (
        <div className="chip-row">
          {Object.entries(counts)
            .filter(([, n]) => n > 0)
            .map(([name, n]) => (
              <span key={name} className="chip chip-quiet">
                {n} {name.replace("_", " ")}
              </span>
            ))}
        </div>
      )}

      <div className="chip-row">
        <button className="chip chip-hot" onClick={save} disabled={busy}>
          {busy ? "…" : "DOWNLOAD A COPY"}
        </button>
        <button
          className="chip chip-quiet"
          onClick={() => picker.current?.click()}
          disabled={busy}
        >
          RESTORE FROM A FILE
        </button>
      </div>

      {said && <p className="muted small notify-said">{said}</p>}

      <p className="muted small">
        Plain readable JSON — open it in any text editor. Restoring merges:
        anything already here is left alone, so it is safe to run twice.
        Sign-in tokens are deliberately left out.
      </p>

      <input
        ref={picker}
        type="file"
        accept="application/json,.json"
        hidden
        onChange={(e) => load(e.target.files?.[0])}
      />
    </section>
  );
}
