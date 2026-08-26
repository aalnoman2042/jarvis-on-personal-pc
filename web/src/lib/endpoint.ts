/* Where the cloud core actually is.
 *
 * In a browser the HUD is served *by* the core, so relative URLs are correct and
 * the token never crosses an origin. Inside the Android app nothing is served by
 * anyone — the page is loaded from the APK and the origin is localhost — so a
 * relative "/login" would resolve to the phone itself and fail with something
 * unhelpful, on a blank screen, with no console.
 *
 * So the base is explicit: empty in the browser, absolute in the app.
 */

const FALLBACK = "https://vondo-core.onrender.com";

function nativeShell(): boolean {
  const cap = (window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor;
  if (cap?.isNativePlatform) return cap.isNativePlatform();
  // Belt and braces: Capacitor serves the page from these schemes/hosts, and a
  // plugin failing to load must not silently turn the app back into "relative".
  return location.protocol === "capacitor:" || location.hostname === "localhost";
}

/** "" in a browser, "https://…" in the app. Never ends with a slash. */
export function apiBase(): string {
  const configured = import.meta.env.VITE_API_BASE as string | undefined;
  if (configured) return configured.replace(/\/$/, "");
  return nativeShell() ? FALLBACK : "";
}

/** The websocket origin, derived from the same decision. */
export function socketBase(): string {
  const base = apiBase();
  if (base) return base.replace(/^http/, "ws");
  return `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}`;
}

/** True when running inside the Android app rather than a browser tab. */
export const isApp = nativeShell();
