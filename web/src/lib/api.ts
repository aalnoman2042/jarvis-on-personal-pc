/* The few things that are plain HTTP rather than the socket: pairing, and a
 * status read before the socket is up. Same origin in production, proxied by
 * Vite in development, so these are all relative URLs.
 */

import { apiBase } from "./endpoint";

async function post(path: string, body: unknown, token?: string) {
  const res = await fetch(apiBase() + path, {
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

export async function health() {
  const res = await fetch(apiBase() + "/health");
  return res.json();
}
