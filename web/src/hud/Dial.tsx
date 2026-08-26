/* A measured value as a ring with the number inside it.
 *
 * The bar it replaces was honest and dull. A ring reads as an instrument, which
 * is most of what the reference screenshots are doing — and it earns the space
 * by putting the figure at a size you can read from across a desk, which is the
 * actual use: glancing at a second monitor to see whether the machine is busy.
 *
 * The decimal is set small and raised, the way an instrument prints it, so the
 * whole number stays the thing you read and the precision is available without
 * competing for attention.
 *
 * SVG rather than canvas, deliberately. There is one of these per reading and
 * they change every few seconds; a canvas would mean another animation loop for
 * something CSS can transition. The reactor earns its loop, this does not.
 *
 * The unknown case draws an empty track and a dash — never a zero. Zero is a
 * reading, nothing is not, and drawing one as the other is how a board ends up
 * confidently reporting an unreachable PC as idle.
 */

const SIZE = 96;
const STROKE = 6;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

// The ring is a three-quarter sweep with a gap at the bottom, the way a dial is
// drawn — a full circle reads as a pie chart.
const SWEEP = 0.75;

const CAUTION = 80;
const ALARM = 92;

export function Dial({ label, value, unit = "%", invert = false }: {
  label: string;
  /** 0–100, or undefined when there is no reading at all. */
  value?: number;
  unit?: string;
  /** For things where low is the bad end — a battery. */
  invert?: boolean;
}) {
  const known = typeof value === "number" && Number.isFinite(value);
  const pct = known ? Math.max(0, Math.min(100, value)) : 0;
  const severity = invert ? 100 - pct : pct;
  const tone = severity >= ALARM ? "bad" : severity >= CAUTION ? "warn" : "ok";

  const whole = Math.floor(pct);
  const fraction = Math.round((pct - whole) * 100);

  const track = CIRCUMFERENCE * SWEEP;
  const filled = track * (pct / 100);

  return (
    <div className={`dial dial-${tone}`}>
      <svg
        className="dial-svg"
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="meter"
        aria-valuenow={known ? whole : undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        {/* Rotated so the gap sits at the bottom and the sweep starts lower-left. */}
        <g transform={`rotate(135 ${SIZE / 2} ${SIZE / 2})`}>
          <circle
            className="dial-track"
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            strokeWidth={STROKE}
            strokeDasharray={`${track} ${CIRCUMFERENCE}`}
          />
          <circle
            className="dial-fill"
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            strokeWidth={STROKE}
            strokeDasharray={`${filled} ${CIRCUMFERENCE}`}
          />
        </g>
      </svg>
      <div className="dial-read">
        {known ? (
          <span className="dial-number mono">
            {whole}
            <sup className="dial-frac">{String(fraction).padStart(2, "0")}</sup>
          </span>
        ) : (
          <span className="dial-number dial-none mono">&mdash;</span>
        )}
        <span className="dial-unit label">{known ? unit : ""}</span>
      </div>
      <span className="dial-label label">{label}</span>
    </div>
  );
}
