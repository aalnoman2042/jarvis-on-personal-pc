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

/** Everything the settings screen shows, in one round trip. */
export async function me(token: string) {
  const res = await fetch(apiBase() + "/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Could not load settings");
  return res.json();
}

/** Drop something Jarvis remembers. */
export function forgetFact(token: string, fragment: string) {
  return post("/facts/forget", { fragment }, token);
}

/** A recorded clip in, the words in it out.

    Multipart rather than JSON so the audio is not base64-inflated by a third on
    a connection that may be a phone on mobile data. No Content-Type is set on
    purpose: the browser has to add the multipart boundary itself. */
export async function transcribe(token: string, clip: Blob): Promise<string> {
  const form = new FormData();
  form.append("clip", clip, "clip.webm");
  const res = await fetch(apiBase() + "/listen", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!res.ok) {
    if (res.status === 503) throw new Error("Speech isn't configured on the server.");
    throw new Error("Couldn't hear that just now.");
  }
  const data = await res.json();
  return (data.text || "").trim();
}

/** What is coming up. */
export async function agenda(token: string) {
  const res = await fetch(apiBase() + "/agenda", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Could not load the diary");
  return res.json();
}

/** Add something without going through a brain — a form, not a conversation. */
export function addAgenda(token: string, when: string, message: string, warn = "") {
  return post("/agenda", { when, message, warn }, token);
}

export async function dropAgenda(token: string, id: number) {
  const res = await fetch(`${apiBase()}/agenda/${id}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Could not remove that");
  return res.json();
}
