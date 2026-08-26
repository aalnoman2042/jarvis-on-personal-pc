/* One measured value, as a labelled bar.
 *
 * A bar rather than a dial because these are read at a glance from across a
 * desk, and a bar tells you "how full" in one saccade where a dial asks you to
 * find the needle first.
 *
 * A value that has not arrived draws as an empty track with a dash, never as
 * zero. Zero is a reading; nothing is not, and drawing one as the other is how
 * a screen ends up confidently reporting that an unreachable PC is idle.
 */

const CAUTION = 80; // above this the bar goes amber
const ALARM = 92;

export function Gauge({ label, value, invert = false }: {
  label: string;
  /** 0–100, or undefined when there is no reading. */
  value?: number;
  /** For things where low is the bad end — a battery. */
  invert?: boolean;
}) {
  const known = typeof value === "number" && Number.isFinite(value);
  const pct = known ? Math.max(0, Math.min(100, value)) : 0;
  const severity = invert ? 100 - pct : pct;
  const tone = severity >= ALARM ? "bad" : severity >= CAUTION ? "warn" : "ok";

  return (
    <div className="gauge">
      <span className="gauge-label label">{label}</span>
      <span
        className={`gauge-track gauge-${tone}`}
        role="meter"
        aria-valuenow={known ? Math.round(pct) : undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        <span className="gauge-fill" style={{ width: `${pct}%` }} />
      </span>
      <span className="gauge-value mono">{known ? `${Math.round(pct)}%` : "—"}</span>
    </div>
  );
}
