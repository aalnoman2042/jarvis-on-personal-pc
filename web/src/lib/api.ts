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
  // Retried once, because the free tier sleeps and the very request that wakes
  // it comes back a 502 or 504 during the ~minute it takes to start. Giving up
  // on that first answer — which is what "Couldn't hear that" used to mean most
  // of the time — throws away a clip the server would have handled a moment
  // later. The second attempt waits for it to be up.
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const form = new FormData();
    form.append("clip", clip, "clip.webm");
    let res: Response;
    try {
      res = await fetch(apiBase() + "/listen", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
    } catch {
      // A dropped connection or a cold-start timeout. Worth one more try.
      if (attempt === 0) {
        await new Promise((r) => setTimeout(r, 1500));
        continue;
      }
      throw new Error("No link to the core — check your signal.");
    }

    if (res.ok) {
      const data = await res.json();
      return (data.text || "").trim();
    }
    if (res.status === 503) throw new Error("Speech isn't set up on the server.");
    if (res.status === 413) throw new Error("That was a bit long — keep it short.");
    if (res.status === 429) throw new Error("One moment — too many in a row.");
    if (res.status === 401) throw new Error("Sign-in expired — enter your PIN again.");
    // 5xx from a waking free tier: pause and try the second attempt.
    if (res.status >= 500 && attempt === 0) {
      await new Promise((r) => setTimeout(r, 2500));
      continue;
    }
    // The status is in the message on purpose: every remaining cause is a
    // different number (502 waking, 422 bad upload, 400 bad request), and one
    // catch-all sentence has already cost two rounds of guessing.
    let detail = "";
    try {
      detail = (await res.json())?.detail || "";
    } catch {
      /* body was not json */
    }
    throw new Error(`The core answered ${res.status}${detail ? ` (${detail})` : ""}.`);
  }
  throw new Error("The core didn't answer after two tries.");
}

/** An image in, a description out. The honest half of the face-scan panel:
    Gemini says what is in the frame — reads the text, describes the scene —
    rather than identifying anyone. `question` is optional; empty means "what
    is this". */
export async function look(token: string, image: Blob, question = ""): Promise<string> {
  const form = new FormData();
  form.append("clip", image, "image.jpg");
  form.append("question", question);
  const res = await fetch(apiBase() + "/look", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!res.ok) {
    if (res.status === 503) throw new Error("Vision isn't set up on the server.");
    if (res.status === 413) throw new Error("That image is too large.");
    let detail = "";
    try {
      detail = (await res.json())?.detail || "";
    } catch {
      /* not json */
    }
    throw new Error(detail || `The core answered ${res.status}.`);
  }
  const data = await res.json();
  return (data.said || "").trim();
}

/** Today, before anyone asks. `fresh` says it is the first of a new day. */
export async function brief(token: string): Promise<{ text: string; fresh: boolean }> {
  const res = await fetch(apiBase() + "/brief", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Couldn't load today");
  return res.json();
}

/** Mark it read, so it does not reappear for the rest of the day. */
export function briefSeen(token: string) {
  return post("/brief/seen", {}, token);
}

/** The inboxes, ranked. Nothing is fetched until this is called: it is an IMAP
    round-trip per account, which is too slow to do on every board load. */
export async function mail(token: string, days = 2) {
  const res = await fetch(`${apiBase()}/mail?days=${days}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Could not read the mailboxes");
  return res.json() as Promise<{
    configured: boolean;
    count: number;
    said: string;
    messages: import("./types").MailMessage[];
  }>;
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
