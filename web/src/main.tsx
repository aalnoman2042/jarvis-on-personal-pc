import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { isApp } from "./lib/endpoint";
import { trackViewport } from "./lib/viewport";
import "./fonts.css";
import "./theme.css";
import "./hud.css";

// Before first paint, so the shell is never laid out against a height that is
// about to change.
trackViewport();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// The service worker is what makes this open with no signal and what receives
// push notifications. Registered after paint so it never delays first render,
// and only on a secure origin — browsers refuse it over plain http anyway, and
// the console error looks like a bug rather than the rule it is.
// Skipped inside the Android app: the assets are already in the APK, and a
// worker caching a localhost origin would shadow them on the next launch.
if (!isApp && "serviceWorker" in navigator && location.protocol === "https:") {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.warn("[vondo] service worker did not register:", err);
    });
  });
}
