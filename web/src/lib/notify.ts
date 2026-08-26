/* Making a reminder arrive when the app is shut.
 *
 * The server can only push down a websocket, and a websocket exists only while
 * the app is open. That was fine for "in twenty minutes" while you sit there
 * and useless for the thing this was built for: an exam on the 18th, warned
 * about on the 17th, with the phone in a pocket.
 *
 * Push is the obvious answer and the wrong one here. Inside the APK the page
 * runs in a WebView, where the Web Push API does not exist; the native route is
 * Firebase, which means an account, a project, a google-services.json in the
 * repo and a Google dependency in something that deliberately has none.
 *
 * So the diary is mirrored onto the device and the OS holds the alarms. They
 * fire with the app closed, the phone offline and the free-tier server asleep —
 * the three conditions the old design was guaranteed to fail under. The cloud
 * stays the source of truth; the phone keeps a cache with a clock.
 *
 * Everything here is observable on purpose. `state()` reports exactly what is
 * and is not working, and `test()` fires one in a few seconds — because a
 * notification system whose only test is missing something important is not a
 * system anyone can trust, and it was one until now.
 */
import type { AgendaItem } from "./types";

/** Our alarms occupy an id space of their own; OS ids are global. */
const ID_BASE = 720000;
const TEST_ID = ID_BASE - 1;

/** Far-future items are not scheduled: Android caps how many alarms one app may
    hold, and something eight months out will be re-synced hundreds of times
    before it matters. */
const HORIZON_DAYS = 60;

/** Long enough to lock the phone and watch it arrive, short enough to wait for. */
const TEST_DELAY_MS = 8000;

/** Its own channel so the importance, sound and vibration are ours to set.
    Left to the default channel, Android is free to decide a reminder is a
    low-priority silent thing, which for the one feature that has to interrupt
    you is precisely wrong. */
const CHANNEL = "vondo-reminders";

type Plugin = typeof import("@capacitor/local-notifications").LocalNotifications;

export type Permission = "granted" | "denied" | "prompt" | "unsupported";

export interface NotifyState {
  /** Running inside the Android app, where alarms survive the app closing. */
  native: boolean;
  permission: Permission;
  /** Alarms the OS is currently holding for us. */
  scheduled: number;
  /** Android 12+ can withhold exact timing separately from notifications.
      null when the platform does not have the concept. */
  exact: boolean | null;
  /** Whether the high-importance channel exists. A notification posted to a
      channel that does not exist is dropped by Android without any error. */
  channel: boolean | null;
  /** Plain-English reason it will not work, or "" when it will. */
  problem: string;
}

function isNative(): boolean {
  const cap = (window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor;
  return Boolean(cap?.isNativePlatform?.());
}

async function plugin(): Promise<Plugin | null> {
  if (!isNative()) return null;
  try {
    const mod = await import("@capacitor/local-notifications");
    return mod.LocalNotifications;
  } catch {
    // A build without the plugin degrades to "no notifications", never to a
    // white screen.
    return null;
  }
}

/* Whether the channel actually exists.
 *
 * This is load-bearing and was a bug. On Android 8 and later, a notification
 * posted to a channel id that does not exist is DROPPED — no error, no entry in
 * the tray, nothing to see. The old code created the channel inside a try that
 * swallowed failures and then set `channelId` on every notification regardless,
 * so any platform or plugin version where createChannel did not work produced
 * exactly the symptom Rohan had: permission granted, alarm scheduled, nothing
 * on the lock screen.
 *
 * So the id is only ever attached when the channel is known to be there. */
let channelReady: boolean | null = null;

async function ensureChannel(api: Plugin): Promise<boolean> {
  if (channelReady !== null) return channelReady;
  try {
    if (!api.createChannel) {
      channelReady = false;      // iOS, or a plugin without channels
      return channelReady;
    }
    await api.createChannel({
      id: CHANNEL,
      name: "Reminders",
      description: "Things Jarvis is keeping for you",
      importance: 5,        // max: heads-up, makes a sound
      visibility: 1,        // shows on the lock screen
      vibration: true,
    });
    // Trust the listing, not the call: createChannel resolving does not by
    // itself prove the channel is registered.
    const listed = await api.listChannels?.();
    channelReady = listed
      ? listed.channels.some((c) => c.id === CHANNEL)
      : true;
  } catch {
    channelReady = false;
  }
  return channelReady;
}

/** The channel id to post with, or undefined to let Android use its default. */
async function channelFor(api: Plugin): Promise<string | undefined> {
  return (await ensureChannel(api)) ? CHANNEL : undefined;
}

/**
 * Ask for permission to notify.
 *
 * Called when notifications are actually set up rather than on first launch:
 * a prompt for a feature you have not used yet is the one people refuse out of
 * hand, and Android only asks once.
 */
export async function askPermission(): Promise<boolean> {
  const api = await plugin();
  if (api) {
    try {
      await ensureChannel(api);
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

/** Everything that decides whether a reminder will actually arrive. */
export async function state(): Promise<NotifyState> {
  const native = isNative();
  const api = await plugin();

  if (!api) {
    const browser: Permission =
      typeof Notification === "undefined"
        ? "unsupported"
        : (Notification.permission as Permission);

    // Being inside the app with no alarm plugin is a completely different
    // problem from being in a browser tab, and reporting them the same way sent
    // everyone looking in the wrong place. It means the installed APK was built
    // before the plugin existed — the web half updates itself from the cloud,
    // the native half cannot — so reminders show up inside the app (the socket
    // still works) and never reach the notification bar.
    if (native) {
      return {
        native: true,
        permission: browser,
        scheduled: 0,
        exact: null,
        channel: null,
        problem:
          "This app build has no alarm support, so reminders can only appear "
          + "while it is open. Uninstall Jarvis and install the newest APK — "
          + "screens update themselves, this part cannot.",
      };
    }

    return {
      native: false,
      permission: browser,
      scheduled: 0,
      exact: null,
      channel: null,
      problem:
        browser === "granted"
          ? "In a browser these only arrive while this tab is open. Install the app for reminders that arrive with it closed."
          : browser === "denied"
            ? "Notifications are blocked for this site in your browser settings."
            : "Notifications have not been allowed yet.",
    };
  }

  let permission: Permission = "prompt";
  let scheduled = 0;
  let exact: boolean | null = null;
  const channel = await ensureChannel(api);
  try {
    permission = (await api.checkPermissions()).display as Permission;
  } catch {
    permission = "unsupported";
  }
  try {
    const held = await api.getPending();
    scheduled = held.notifications.filter((n) => n.id >= ID_BASE).length;
  } catch {
    /* leave at zero */
  }
  try {
    // Android 12 introduced a separate permission for alarms that fire at an
    // exact moment. Without it the OS may delay a reminder by minutes to batch
    // it, which for "your exam is tomorrow" is survivable and for "leave in ten
    // minutes" is not. Feature-detected: older plugins have no such call.
    const check = (api as unknown as {
      checkExactNotificationSetting?: () => Promise<{ exact_alarm: string }>;
    }).checkExactNotificationSetting;
    if (check) exact = (await check()).exact_alarm === "granted";
  } catch {
    exact = null;
  }

  let problem = "";
  if (permission === "denied") {
    problem = "Notifications are switched off for Jarvis in Android settings.";
  } else if (permission !== "granted") {
    problem = "Notifications have not been allowed yet.";
  } else if (channel === false) {
    problem = "Allowed, but the reminder channel is missing — Android drops "
      + "notifications posted to a channel that does not exist. Falling back to "
      + "the default channel.";
  } else if (exact === false) {
    problem = "Allowed, but Android may delay them — exact alarms are off for Jarvis.";
  }

  return { native, permission, scheduled, exact, channel, problem };
}

/** Open the Android page where exact alarms can be switched on. */
export async function fixExact(): Promise<void> {
  const api = await plugin();
  const change = (api as unknown as {
    changeExactNotificationSetting?: () => Promise<unknown>;
  })?.changeExactNotificationSetting;
  try {
    await change?.();
  } catch {
    /* nothing else to offer; the state readout still says what is wrong */
  }
}

/**
 * Fire one in a few seconds, so "does this work?" has an answer.
 *
 * Deliberately delayed rather than immediate: the point is to lock the phone
 * and watch it arrive on the lock screen, which is the thing that actually
 * needs proving. An instant one only proves the app can talk to itself.
 */
export async function test(): Promise<string> {
  const allowed = await askPermission();
  if (!allowed) return "Permission was refused, so nothing can arrive.";

  const api = await plugin();
  if (!api) {
    if (typeof Notification === "undefined") return "This browser cannot show notifications.";
    try {
      new Notification("Jarvis", {
        body: "This is a test. Reminders will look like this.",
        icon: "/icon-192.png",
      });
      return "Sent. In a browser it only shows while this tab is open.";
    } catch {
      return "The browser refused to show it.";
    }
  }

  try {
    const channelId = await channelFor(api);
    await api.schedule({
      notifications: [{
        id: TEST_ID,
        title: "Jarvis",
        body: "Test reminder — this is what they will look like.",
        ...(channelId ? { channelId } : {}),
        schedule: { at: new Date(Date.now() + TEST_DELAY_MS), allowWhileIdle: true },
      }],
    });
    // Read it back. schedule() resolving means the call was accepted, not that
    // the OS is holding an alarm — and the difference between those two is
    // precisely the failure that is impossible to see from the outside.
    const held = await api.getPending();
    const landed = held.notifications.some((n) => n.id === TEST_ID);
    if (!landed) {
      return "Android accepted it but is not holding it — check battery "
        + "optimisation for Jarvis, which can drop scheduled alarms.";
    }
    return "On its way. Lock your phone — it should arrive in about eight seconds.";
  } catch (err) {
    return `Could not schedule it: ${err instanceof Error ? err.message : "unknown"}`;
  }
}

/* What was last mirrored onto the device. `syncAlarms` used to cancel and
 * reschedule everything on every load of the board — which happens after every
 * answer — so a conversation of ten turns rewrote the alarm table ten times for
 * no change at all. Comparing a cheap signature first makes the common case
 * free. */
let lastSignature = "";

function signature(items: AgendaItem[]): string {
  return items
    .map((i) => `${i.id}:${Math.round(i.remind_at || i.due)}:${i.message.length}`)
    .join("|");
}

/**
 * Mirror the diary onto the device.
 *
 * Silently does nothing outside the Android app — a browser tab has no business
 * holding alarms it cannot fire once it is closed.
 */
export async function syncAlarms(items: AgendaItem[], force = false): Promise<number> {
  const api = await plugin();
  if (!api) return 0;

  const now = Date.now();
  const horizon = now + HORIZON_DAYS * 86400_000;
  const wanted = items
    .map((item) => ({ item, at: (item.remind_at || item.due) * 1000 }))
    .filter(({ at }) => at > now + 5_000 && at < horizon);

  const sig = signature(wanted.map((w) => w.item));
  if (!force && sig === lastSignature) return wanted.length;

  try {
    const channelId = await channelFor(api);
    const held = await api.getPending();
    // The test alarm is ours too but is not part of the diary, so it is left
    // alone — cancelling it here would make "send a test" and "open the board"
    // race each other.
    const ours = held.notifications.filter((n) => n.id >= ID_BASE);
    if (ours.length) await api.cancel({ notifications: ours.map((n) => ({ id: n.id })) });

    if (wanted.length) {
      await api.schedule({
        notifications: wanted.map(({ item, at }) => ({
          id: ID_BASE + (item.id % 100000),
          title: item.kind === "event" ? "Coming up" : "Jarvis",
          body: item.said || item.message,
          ...(channelId ? { channelId } : {}),
          schedule: { at: new Date(at), allowWhileIdle: true },
          extra: { agendaId: item.id },
        })),
      });
    }
    lastSignature = sig;
    return wanted.length;
  } catch {
    // A refused permission or a full alarm table is not worth breaking the
    // board over: the websocket path still delivers while the app is open.
    return 0;
  }
}
