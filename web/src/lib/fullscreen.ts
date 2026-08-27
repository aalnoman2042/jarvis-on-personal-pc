/* Using the whole screen inside the Android app.
 *
 * The web manifest's `display: fullscreen` governs the INSTALLED PWA and has no
 * say whatever over the APK — that is a native setting, and it was never set.
 * So the app kept a system status bar above it and could not reach the top of
 * the screen no matter what the manifest claimed.
 *
 * Two parts. `overlaysWebView` in capacitor.config puts the page behind the
 * bar rather than below it; this hides the bar as well, which is what makes a
 * HUD feel like a HUD rather than a page in a frame.
 *
 * The gesture bar at the bottom is deliberately left alone. Hiding it means
 * sticky-immersive mode, where the first swipe anywhere brings it back instead
 * of doing what you meant — and on a screen whose main gesture is swiping a
 * reply away, that trade is plainly wrong.
 *
 * Everything is best-effort: on a device or build without the plugin the app
 * simply keeps its status bar, which is a cosmetic loss and nothing more.
 */

function isNative(): boolean {
  const cap = (window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor;
  return Boolean(cap?.isNativePlatform?.());
}

export async function goFullscreen(): Promise<void> {
  if (!isNative()) return;
  try {
    const { StatusBar, Style } = await import("@capacitor/status-bar");
    // Overlay first, then hide. Hiding alone leaves the layout still inset by
    // the height of a bar that is no longer there — a black band at the top
    // that looks like a rendering fault.
    await StatusBar.setOverlaysWebView({ overlay: true });
    await StatusBar.setStyle({ style: Style.Dark });
    await StatusBar.hide();
  } catch {
    /* no plugin in this build; the app keeps its status bar */
  }
}

/** Android brings the bar back after some system interactions. */
export function keepFullscreen(): void {
  if (!isNative()) return;
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) goFullscreen();
  });
}
