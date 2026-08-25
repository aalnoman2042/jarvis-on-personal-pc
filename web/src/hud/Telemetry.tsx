/* The gutter: what Rohan's PC is doing right now.
 *
 * Fed by the agent's telemetry frames. When the PC is asleep this does not
 * vanish — it greys out and says so. A panel that disappears reads as a bug;
 * a panel that says "PC offline" reads as an answer.
 */
import type { Telemetry as TelemetryData } from "../lib/types";

function Meter({ label, value, unit = "%" }: { label: string; value?: number; unit?: string }) {
  const known = typeof value === "number";
  const pct = known ? Math.max(0, Math.min(100, value)) : 0;
  // Amber past 75, red past 90 — semantic, and separate from the accent hue so
  // "busy" never reads as "highlighted".
  const tone = pct > 90 ? "var(--bad)" : pct > 75 ? "var(--warn)" : "var(--accent)";
  return (
    <div className="meter">
      <div className="meter-head">
        <span className="label">{label}</span>
        <span className="mono meter-value">{known ? `${Math.round(pct)}${unit}` : "--"}</span>
      </div>
      <div className="meter-track">
        <div
          className="meter-fill"
          style={{ width: `${pct}%`, background: tone, boxShadow: `0 0 10px ${tone}` }}
        />
      </div>
    </div>
  );
}

export function Telemetry({ data, online }: { data: TelemetryData; online: boolean }) {
  return (
    <aside className={`gutter bracket${online ? "" : " gutter-off"}`}>
      <header className="gutter-head">
        <span className="label">This PC</span>
        <span className={`dot ${online ? "dot-on" : "dot-off"}`} aria-hidden />
      </header>

      {online ? (
        <>
          <Meter label="CPU" value={data.cpu} />
          <Meter label="Memory" value={data.memory} />
          {typeof data.battery === "number" && (
            <Meter label={data.charging ? "Battery (charging)" : "Battery"} value={data.battery} />
          )}
        </>
      ) : (
        <p className="gutter-note">
          Asleep. Everything except opening apps and reading this PC still works.
        </p>
      )}
    </aside>
  );
}
