/* Installing Jarvis to the home screen.
 *
 * Chrome fires `beforeinstallprompt` when it decides a site is installable, and
 * left alone it may or may not surface a banner — it weighs engagement heuristics
 * and often stays silent on a first visit. That is fine for a shop; it is wrong
 * for something you built for yourself and want on your home screen now.
 *
 * So the event is captured, its default banner suppressed, and the prompt held
 * until a button asks for it. That is the supported way to own the moment: the
 * saved event can be fired once, from a real user gesture.
 */
import { useEffect, useState } from "react";

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let waiting: InstallPromptEvent | null = null;
const listeners = new Set<(ready: boolean) => void>();

function announce(ready: boolean) {
  listeners.forEach((fn) => fn(ready));
}

// Registered at module load, not inside a component: the event fires early, and
// a listener attached after React has mounted routinely misses it.
if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    waiting = event as InstallPromptEvent;
    announce(true);
  });
  window.addEventListener("appinstalled", () => {
    waiting = null;
    announce(false);
  });
}

/** True when the app is already running from the home screen. */
export function isInstalled(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    // Safari's own flag; harmless to check on Android.
    (window.navigator as unknown as { standalone?: boolean }).standalone === true
  );
}

export function useInstall() {
  const [ready, setReady] = useState(() => waiting !== null);
  const [installed, setInstalled] = useState(isInstalled);

  useEffect(() => {
    listeners.add(setReady);
    return () => {
      listeners.delete(setReady);
    };
  }, []);

  async function install() {
    if (!waiting) return;
    await waiting.prompt();
    const { outcome } = await waiting.userChoice;
    // A saved prompt can only be used once, whichever way it went.
    waiting = null;
    announce(false);
    if (outcome === "accepted") setInstalled(true);
  }

  return { canInstall: ready && !installed, installed, install };
}
