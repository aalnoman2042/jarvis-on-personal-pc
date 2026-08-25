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
