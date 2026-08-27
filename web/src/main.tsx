import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { bundledShell, nativeShell } from "./lib/endpoint";
import { goFullscreen, keepFullscreen } from "./lib/fullscreen";
import { trackViewport } from "./lib/viewport";
import "./fonts.css";
import "./theme.css";
import "./hud.css";

// Before first paint, so the shell is never laid out against a height that is
// about to change.
trackViewport();

// The whole screen, in the app. Done before render so the first frame is
// already the right size rather than resizing under the boot sequence.
goFullscreen();
keepFullscreen();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

/* The splash screen is held until there is something to show.
 *
 * The Android app loads its screens over the network now, so between the icon
 * being tapped and React mounting there is a real request — and on a free tier
 * that has been asleep, that request can take the better part of a minute. On a
 * timed splash the user would watch it vanish into a white screen and conclude
 * the app was broken. Held, they watch the splash, which is what a slow launch
 * is supposed to look like.
 */
if (nativeShell()) {
  import("@capacitor/splash-screen")
    .then(({ SplashScreen }) => SplashScreen.hide())
    .catch(() => {
      /* no plugin in this build; the launch config hides it on a timer anyway */
    });
}

/* The service worker is what makes this open with no signal.
 *
 * Registered after paint so it never delays first render, and only on a real
 * secure origin. It used to be skipped in the Android app entirely, because the
 * app served its screens from Capacitor's own origin where a worker will not
 * run. The app loads from the cloud now, which is an ordinary HTTPS origin — so
 * the app finally gets the offline cache the browser has always had, and this
 * is what stops it needing the network on every launch.
 */
if (!bundledShell() && "serviceWorker" in navigator && location.protocol === "https:") {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/sw.js")
      .then((reg) => {
        // The shell is served from cache first now, so a new build is on the
        // device an entire launch before it is on screen. Reloading once the
        // replacement has taken over closes that gap without the jarring
        // mid-session refresh that reloading immediately would cause.
        reg.addEventListener("updatefound", () => {
          const next = reg.installing;
          if (!next) return;
          next.addEventListener("statechange", () => {
            if (next.state === "installed" && navigator.serviceWorker.controller) {
              // Only when the page is out of sight: reloading under someone
              // mid-sentence is worse than showing them yesterday's build for
              // another minute.
              document.addEventListener("visibilitychange", () => {
                if (document.hidden) location.reload();
              }, { once: true });
            }
          });
        });
        // Look for one on every launch rather than trusting the browser's own
        // schedule, which can be a day.
        reg.update().catch(() => {});
      })
      .catch((err) => {
        console.warn("[vondo] service worker did not register:", err);
      });
  });
}
