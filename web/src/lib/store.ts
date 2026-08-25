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

export function deviceName(): string {
  try {
    const saved = localStorage.getItem(NAME);
    if (saved) return saved;
  } catch {
    /* fall through to a guess */
  }
  const guess = /Android|iPhone|iPad/i.test(navigator.userAgent) ? "phone" : "desktop";
  try {
    localStorage.setItem(NAME, guess);
  } catch {
    /* ignore */
  }
  return guess;
}
