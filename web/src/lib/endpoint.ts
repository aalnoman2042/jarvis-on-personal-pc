/* Where the cloud core actually is, and where this page came from.
 *
 * Two different questions, and conflating them was a bug waiting to happen.
 *
 * The Android app loads the HUD *from* the cloud core rather than from inside
 * the APK, so that pushing a change updates the app without anyone downloading
 * anything. The page's origin is therefore the core itself, relative URLs are
 * correct, and — because it is a real HTTPS origin rather than Capacitor's
 * localhost — the service worker works, which is what keeps it opening with no
 * signal.
 *
 * The bundled copy still exists as the fallback Capacitor shows when the cloud
 * cannot be reached at all (`server.errorPath`). That copy runs on
 * https://localhost, where a relative "/login" would resolve to the phone
 * itself, so it needs the absolute address instead.
 *
 * Hence: the question is not "is this the app" but "did this page come out of
 * the APK".
 */

const FALLBACK = "https://vondo-core.onrender.com";

/** True when running inside the Android app rather than a browser tab. */
export function nativeShell(): boolean {
  const cap = (window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor;
  return Boolean(cap?.isNativePlatform?.());
}

/**
 * True when this page was loaded from files inside the APK rather than over the
 * network — Capacitor's own origin. Note this stays false in the normal app,
 * which now loads from the cloud like a browser does.
 */
export function bundledShell(): boolean {
  // Both halves matter. Capacitor's bundled origin is https://localhost with no
  // port; so is `npm run dev`, near enough, and there a relative URL is right
  // because Vite proxies it. Requiring the native bridge as well separates the
  // two without a fragile guess about port numbers.
  if (!nativeShell()) return false;
  return location.protocol === "capacitor:" || location.hostname === "localhost";
}

/** "" when the page and the API share an origin, "https://…" when they do not. */
export function apiBase(): string {
  const configured = import.meta.env.VITE_API_BASE as string | undefined;
  if (configured) return configured.replace(/\/$/, "");
  return bundledShell() ? FALLBACK : "";
}

/** The websocket origin, derived from the same decision. */
export function socketBase(): string {
  const base = apiBase();
  if (base) return base.replace(/^http/, "ws");
  return `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}`;
}

export const isApp = nativeShell();
