/* The one thing the HUD remembers between visits: its device token.
 *
 * localStorage rather than a cookie, because the token is used from JavaScript
 * (the websocket takes it as a query parameter) and a cookie would buy nothing.
 * Every access is wrapped: private windows and "block site data" make these
 * throw rather than return null, and a HUD that white-screens because storage
 * is switched off would be a poor way to find that out.
 */

const TOKEN = "vondo.token";
const NAME = "vondo.device";

export function readToken(): string {
  try {
    return localStorage.getItem(TOKEN) ?? "";
  } catch {
    return "";
  }
}

export function writeToken(token: string) {
  try {
    localStorage.setItem(TOKEN, token);
  } catch {
    /* the session still works, it just will not be remembered */
  }
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN);
  } catch {
    /* ignore */
  }
}

/** A name you could pick out of a list, from what the browser will admit to.
 *
 * It used to be "phone" or "desktop", which was fine while the list was
 * read-only and became a problem the moment devices could be revoked from it:
 * three rows all called "phone" and no way to tell which one you are about to
 * sign out of. So the browser and the platform go in the name.
 *
 * Deliberately coarse. The user-agent string can identify a browser far more
 * precisely than this, and none of that extra precision helps somebody looking
 * at five rows deciding which is the old tablet — while all of it is a
 * fingerprint stored on a server. "Chrome on Android" is what a person would
 * say out loud, and it is enough.
 */
function guessName(): string {
  const ua = navigator.userAgent || "";
  // Order matters: every one of these contains "Safari", and most contain
  // "Chrome", so the most specific has to be tested first.
  const browser =
    /Edg\//.test(ua) ? "Edge"
      : /OPR\/|Opera/.test(ua) ? "Opera"
        : /SamsungBrowser/.test(ua) ? "Samsung Internet"
          : /Firefox\//.test(ua) ? "Firefox"
            : /Chrome\//.test(ua) ? "Chrome"
              : /Safari\//.test(ua) ? "Safari"
                : "";
  const platform =
    /Android/.test(ua) ? "Android"
      : /iPhone|iPod/.test(ua) ? "iPhone"
        : /iPad/.test(ua) ? "iPad"
          : /Windows/.test(ua) ? "Windows"
            : /Mac OS X/.test(ua) ? "Mac"
              : /Linux/.test(ua) ? "Linux"
                : "";
  if (browser && platform) return `${browser} on ${platform}`;
  if (platform) return platform;
  if (browser) return browser;
  return /Mobi/i.test(ua) ? "phone" : "desktop";
}

export function deviceName(): string {
  try {
    const saved = localStorage.getItem(NAME);
    if (saved) return saved;
  } catch {
    /* fall through to a guess */
  }
  const guess = guessName();
  try {
    localStorage.setItem(NAME, guess);
  } catch {
    /* ignore */
  }
  return guess;
}
