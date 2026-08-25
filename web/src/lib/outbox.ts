/* Things you said while there was no signal.
 *
 * Losing a thought because you were in a lift is a real cost, so anything typed
 * offline is held here and sent the moment the socket comes back. It survives
 * the app being closed, which is the point — you can type a note on the way
 * home, lock the phone, and it goes when you walk in the door.
 *
 * localStorage rather than IndexedDB: this holds a handful of short strings,
 * and IndexedDB's async ceremony would be more code than the feature. If a
 * queued item ever needs to be more than text, that trade changes.
 *
 * Every access is wrapped. A private window or blocked site data makes these
 * throw rather than return empty, and losing the queue is worth a shrug —
 * losing the whole HUD to an unhandled exception is not.
 */

const KEY = "vondo.outbox";
const LIMIT = 50; // a queue longer than this is a bug, not a busy day

export interface Queued {
  id: number;
  text: string;
  at: number;
}

export function read(): Queued[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function write(items: Queued[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(items.slice(-LIMIT)));
  } catch {
    /* out of quota or blocked — the message is still in the log on screen */
  }
}

export function add(text: string): Queued {
  const item: Queued = { id: Date.now() + Math.floor(Math.random() * 1000), text, at: Date.now() };
  write([...read(), item]);
  return item;
}

export function remove(id: number) {
  write(read().filter((item) => item.id !== id));
}

export function clear() {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

export function count(): number {
  return read().length;
}
