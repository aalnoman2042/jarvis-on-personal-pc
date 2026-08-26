/* Making a reminder arrive when the app is shut.
 *
 * The server can only push down a websocket, and a websocket only exists while
 * the app is open. That was fine for "in twenty minutes" while you sit there and
 * useless for the thing this was built for: an exam on the 18th, warned about on
 * the 17th, when the phone is in a pocket.
 *
 * The obvious fix is push, and push is the wrong fix here. Inside the Android
 * app the page runs in a WebView, where the Web Push API does not exist; the
 * native route is Firebase, which means an account, a project, a
 * google-services.json in the repo, and a Google dependency in something that
 * deliberately has none.
 *
 * So the diary is mirrored onto the device instead. The OS holds the alarms and
 * fires them itself, which means they arrive with the app closed, the phone
 * offline, and the free-tier server fast asleep — the three conditions under
 * which the old design was guaranteed to fail. The cloud stays the source of
 * truth; this is a cache with a clock.
 *
 * Rescheduling from scratch each sync is deliberate. Reconciling ids against
 * whatever the OS is already holding is more code and more ways to end up with
 * a duplicate at 6am, and cancelling everything we own first is exactly as
 * correct for a diary this size.
 */
import type { AgendaItem } from "./types";

/** Our alarms occupy a numeric id space of their own; the OS ids are global. */
const ID_BASE = 720000;

/** Far-future items are not scheduled: Android caps how many alarms one app may
    hold, and something eight months out will be re-synced hundreds of times
    before it matters. */
const HORIZON_DAYS = 60;

type Plugin = typeof import("@capacitor/local-notifications").LocalNotifications;

async function plugin(): Promise<Plugin | null> {
  const cap = (window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor;
  if (!cap?.isNativePlatform?.()) return null;
  try {
    const mod = await import("@capacitor/local-notifications");
    return mod.LocalNotifications;
  } catch {
    // A build without the plugin must degrade to "no notifications", never to a
    // white screen.
    return null;
  }
}

/** Ask once. Android 13 and up refuses to post anything without this. */
export async function askPermission(): Promise<boolean> {
  const api = await plugin();
  if (api) {
    try {
      const current = await api.checkPermissions();
      if (current.display === "granted") return true;
      const asked = await api.requestPermissions();
      return asked.display === "granted";
    } catch {
      return false;
    }
  }
  // In a browser, the same question with a different API. Only useful while the
  // tab is open, which is why the app version is the one that matters.
  if (typeof Notification === "undefined") return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied") return false;
  try {
    return (await Notification.requestPermission()) === "granted";
  } catch {
    return false;
  }
}

/**
 * Mirror the diary onto the device.
 *
 * Silently does nothing outside the Android app — a browser tab has no business
 * holding alarms it cannot fire once it is closed.
 */
export async function syncAlarms(items: AgendaItem[]): Promise<number> {
  const api = await plugin();
  if (!api) return 0;

  const now = Date.now();
  const horizon = now + HORIZON_DAYS * 86400_000;
  const wanted = items
    .map((item) => ({ item, at: (item.remind_at || item.due) * 1000 }))
    .filter(({ at }) => at > now + 5_000 && at < horizon);

  try {
    const held = await api.getPending();
    const ours = held.notifications.filter((n) => n.id >= ID_BASE);
    if (ours.length) await api.cancel({ notifications: ours.map((n) => ({ id: n.id })) });

    if (!wanted.length) return 0;
    await api.schedule({
      notifications: wanted.map(({ item, at }) => ({
        id: ID_BASE + (item.id % 100000),
        title: item.kind === "event" ? "Coming up" : "Jarvis",
        body: item.said || item.message,
        schedule: { at: new Date(at), allowWhileIdle: true },
        // Tapping it should open Jarvis, not a blank screen.
        extra: { agendaId: item.id },
      })),
    });
    return wanted.length;
  } catch {
    // A refused permission or a full alarm table is not worth breaking the
    // board over: the websocket path still delivers while the app is open.
    return 0;
  }
}
