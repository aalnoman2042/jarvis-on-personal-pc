import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "./fonts.css";
import "./theme.css";
import "./hud.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// The service worker is what makes this open with no signal and what receives
// push notifications. Registered after paint so it never delays first render,
// and only on a secure origin — browsers refuse it over plain http anyway, and
// the console error looks like a bug rather than the rule it is.
if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost")) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.warn("[vondo] service worker did not register:", err);
    });
  });
}
