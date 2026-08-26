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

/** Frames the server sends down /ws/client. */
export type ServerFrame =
  | { type: "status"; state: string; brain?: string; pc_online?: boolean }
  | { type: "reply"; reply: string; brain: string; pc_online: boolean }
  | { type: "token"; text: string }
  | ({ type: "telemetry" } & Telemetry)
  | { type: "error"; error: string };

export interface LogLine {
  id: number;
  who: "you" | "jarvis" | "system";
  text: string;
  at: number;
  brain?: string;
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
}
