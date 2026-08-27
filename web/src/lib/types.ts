/* The wire format, written down once.
 *
 * These mirror server/app.py. Keeping them as real types is the reason to have
 * TypeScript here at all: a frame field renamed on the server becomes a compile
 * error rather than something that goes wrong on the phone, in your pocket,
 * with no console open.
 */

export type ConnState = "connecting" | "online" | "offline" | "unauthorised";

export interface Telemetry {
  cpu?: number;
  memory?: number;
  battery?: number;
  charging?: boolean;
  ts?: number;
}

/** One thing in the diary: a reminder, a deadline, an exam. */
export interface AgendaItem {
  id: number;
  due: number;
  remind_at: number;
  message: string;
  all_day: number;
  kind: string;
  fired?: number;
  /** "weekly", "daily", ... or "" for a one-off. */
  repeat_rule?: string;
  /** The same line Jarvis would speak, built on the server so the screen and
      the spoken answer can never disagree about what is in the diary. */
  said: string;
}

/** One message, already ranked by the server. `why` is the reasoning behind
    its place in the list — a ranking you cannot see the reasoning of is one you
    end up double-checking. */
export interface MailMessage {
  account: string;
  from: string;
  address: string;
  subject: string;
  date: number;
  unread: boolean;
  score: number;
  why: string;
}

/** Frames the server sends down /ws/client. */
export type ServerFrame =
  | { type: "status"; state: string; brain?: string; pc_online?: boolean }
  | {
      type: "reply";
      reply: string;
      brain: string;
      pc_online: boolean;
      /** Somewhere the phone was asked to go — a URL or a deep link like
          tel: or whatsapp:. Present only when a tool asked for it. */
      open?: string;
      /** What the full-text index dug out of the archive for this question.
          Shown so a wrong answer can be told apart from a wrong recall. */
      recalled?: { when: number; said: string }[];
    }
  | { type: "token"; text: string }
  | ({ type: "telemetry" } & Telemetry)
  | { type: "reminder"; id: number; text: string; message: string; due: number; all_day: boolean }
  | { type: "error"; error: string };

export interface LogLine {
  id: number;
  who: "you" | "jarvis" | "system";
  text: string;
  at: number;
  brain?: string;
  /** Past exchanges the index surfaced for this answer, if any. */
  recalled?: { when: number; said: string }[];
  /** A picture shown in the conversation. An object URL, so it lives only in
      this tab — the image itself never goes to the database, only what Jarvis
      saw in it. */
  image?: string;
}

/** What the settings screen loads from /me, in one call. */
export interface Me {
  device: { id: string; name: string; kind: string };
  brain: string;
  assistant: string;
  user: string;
  facts: string[];
  remembered: number;
  recent_actions: { ts: number; tool: string; args: string; result: string; ok: number }[];
  pc: { name: string; last_seen: number; telemetry: Telemetry }[];
  devices: { id: string; name: string; kind: string; last_seen: number; revoked: number }[];
  upcoming: AgendaItem[];
  /** Names only — the numbers stay on the server. */
  people: { name: string; phone: boolean; email: boolean }[];
}
