/* The arc reactor.
 *
 * Deliberately plain canvas with no React inside it: this runs sixty times a
 * second and React has no business in that loop. The component owns mounting;
 * this owns drawing.
 *
 * Three rules it has to keep, because "lightweight" was a stated requirement
 * and a HUD that eats a core all day fails it:
 *
 *   1. One canvas, one animation frame. Not a frame per ring.
 *   2. Nothing at all happens while the tab is hidden — the loop stops rather
 *      than drawing into a surface nobody can see.
 *   3. Idle motion is slow and even. It should read as switched-on from the
 *      corner of your eye and never pull it, because this may well sit on a
 *      second monitor beside real work.
 */

export type ReactorState =
  | "offline"
  | "online"
  | "listening"
  | "thinking"
  | "speaking";

/** What the reactor is doing, updated by the app without restarting the loop. */
export interface ReactorInput {
  state: ReactorState;
  /** Microphone loudness, 0..1. Wired up in phase 06; 0 until then. */
  level: number;
}

const COLOURS: Record<ReactorState, { core: string; ring: string }> = {
  offline: { core: "#3a4657", ring: "#22303c" },
  online: { core: "#35d6ff", ring: "#0d7fa3" },
  listening: { core: "#4fe0a8", ring: "#1f9c74" },
  thinking: { core: "#ffb340", ring: "#a3701f" },
  speaking: { core: "#7cc4ff", ring: "#2b6ea8" },
};

/** How fast the whole assembly turns in each state. Idle is deliberately slow. */
const SPIN: Record<ReactorState, number> = {
  offline: 0.05,
  online: 0.3,
  listening: 0.55,
  thinking: 1.45,
  speaking: 0.7,
};

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function mountReactor(canvas: HTMLCanvasElement, input: ReactorInput) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return () => {};

  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let frame = 0;
  let running = true;
  let spun = 0; // accumulated rotation, so a speed change never snaps the rings
  let last = performance.now();
  let glow = 0; // eased loudness, so the core swells rather than flickers

  /** Match the backing store to the CSS size and the screen's pixel density. */
  function resize() {
    const rect = canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2); // 3x costs a lot, shows nothing
    canvas.width = Math.max(1, Math.round(rect.width * dpr));
    canvas.height = Math.max(1, Math.round(rect.height * dpr));
  }

  function arc(cx: number, cy: number, r: number, w: number, from: number, to: number, colour: string, alpha: number) {
    ctx!.beginPath();
    ctx!.globalAlpha = alpha;
    ctx!.strokeStyle = colour;
    ctx!.lineWidth = w;
    ctx!.arc(cx, cy, r, from, to);
    ctx!.stroke();
  }

  function draw(now: number) {
    if (!running) return;
    const dt = Math.min((now - last) / 1000, 0.1); // a backgrounded tab must not lurch
    last = now;

    const { state, level } = input;
    const palette = COLOURS[state];
    spun += dt * SPIN[state] * (still ? 0 : 1);

    // Ease towards the current loudness: fast to rise so speech feels immediate,
    // slow to fall so the core doesn't strobe between syllables.
    const target = Math.max(0, Math.min(1, level));
    glow += (target - glow) * (target > glow ? 0.4 : 0.06);

    const w = canvas.width;
    const h = canvas.height;
    const cx = w / 2;
    const cy = h / 2;
    const R = Math.min(w, h) / 2;
    ctx!.clearRect(0, 0, w, h);

    // Outer broken ring — three arcs with gaps, the classic HUD dial.
    const outer = R * 0.92;
    arc(cx, cy, outer, R * 0.015, spun, spun + 2.1, palette.ring, 0.9);
    arc(cx, cy, outer, R * 0.015, spun + 2.5, spun + 4.5, palette.ring, 0.9);
    arc(cx, cy, outer, R * 0.015, spun + 5.0, spun + 6.05, palette.core, 0.85);

    // Tick marks, turning the other way so the assembly reads as mechanical.
    ctx!.globalAlpha = 0.45;
    ctx!.strokeStyle = palette.ring;
    ctx!.lineWidth = Math.max(1, R * 0.012);
    const ticks = 36;
    for (let i = 0; i < ticks; i++) {
      const a = -spun * 0.7 + (i / ticks) * Math.PI * 2;
      const r0 = R * 0.75;
      const r1 = r0 + R * (i % 3 === 0 ? 0.07 : 0.04);
      ctx!.beginPath();
      ctx!.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0);
      ctx!.lineTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1);
      ctx!.stroke();
    }

    // Two counter-rotating inner arcs.
    const mid = R * 0.62;
    arc(cx, cy, mid, R * 0.022, -spun * 1.7 + 0.3, -spun * 1.7 + 2.4, palette.core, 0.65);
    arc(cx, cy, mid, R * 0.022, -spun * 1.7 + 3.5, -spun * 1.7 + 5.4, palette.core, 0.65);

    // The core itself. Breathing when idle, swelling with your voice when not.
    const breathe = still ? 0.5 : 0.5 + 0.5 * Math.sin(now / 1400);
    const size = R * (0.34 + 0.06 * breathe + 0.22 * glow);
    const [r, g, b] = hexToRgb(palette.core);
    const gradient = ctx!.createRadialGradient(cx, cy, R * 0.02, cx, cy, size);
    gradient.addColorStop(0, "rgba(234,246,255,0.95)");
    gradient.addColorStop(0.3, `rgba(${r},${g},${b},${0.55 + 0.35 * glow})`);
    gradient.addColorStop(1, `rgba(${r},${g},${b},0)`);
    ctx!.globalAlpha = 1;
    ctx!.fillStyle = gradient;
    ctx!.beginPath();
    ctx!.arc(cx, cy, size, 0, Math.PI * 2);
    ctx!.fill();

    // The triangular plate at the centre.
    ctx!.globalAlpha = state === "offline" ? 0.4 : 0.92;
    ctx!.strokeStyle = "#eaf6ff";
    ctx!.lineWidth = Math.max(1.5, R * 0.02);
    ctx!.beginPath();
    for (let i = 0; i < 3; i++) {
      const a = -Math.PI / 2 + (i / 3) * Math.PI * 2 + spun * 0.5;
      const px = cx + Math.cos(a) * R * 0.2;
      const py = cy + Math.sin(a) * R * 0.2;
      if (i === 0) ctx!.moveTo(px, py);
      else ctx!.lineTo(px, py);
    }
    ctx!.closePath();
    ctx!.stroke();
    ctx!.globalAlpha = 1;

    frame = requestAnimationFrame(draw);
  }

  /** Stop dead when the tab is hidden; pick up cleanly when it comes back. */
  function visibility() {
    if (document.hidden) {
      running = false;
      cancelAnimationFrame(frame);
    } else if (!running) {
      running = true;
      last = performance.now();
      frame = requestAnimationFrame(draw);
    }
  }

  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  document.addEventListener("visibilitychange", visibility);
  resize();
  frame = requestAnimationFrame(draw);

  return () => {
    running = false;
    cancelAnimationFrame(frame);
    observer.disconnect();
    document.removeEventListener("visibilitychange", visibility);
  };
}
