/* The few things that are plain HTTP rather than the socket: pairing, and a
 * status read before the socket is up. Same origin in production, proxied by
 * Vite in development, so these are all relative URLs.
 */

async function post(path: string, body: unknown, token?: string) {
  const res = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  let data: any = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

/** Type the PIN, get a device token. The only way in now. */
export function login(pin: string, name: string) {
  return post("/login", { pin, name, kind: "client" });
}

/** Pair the very first device, using the secret set on the server. */
export function bootstrap(secret: string, name: string) {
  return post("/pair/bootstrap", { secret, name, kind: "client" });
}

/** Redeem a six-digit code from an already-paired device. */
export function claim(code: string, name: string) {
  return post("/pair/claim", { code, name, kind: "client" });
}

/** Ask for a code to read out to a new device. */
export function startPairing(token: string) {
  return post("/pair/start", {}, token);
}

export async function health() {
  const res = await fetch("/health");
  return res.json();
}
