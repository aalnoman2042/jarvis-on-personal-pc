/* Things to do, as opposed to things that happen.
 *
 * The diary next to this holds what happens at a time — a class, an exam. This
 * holds what has to get done, which has no time and does have a finished state.
 * Those two differences are why they are separate panels rather than one list
 * with a mixture in it.
 *
 * Ordered by deadline before priority, the same as the store: a normal thing
 * due tomorrow beats an important thing with no date, because the deadline is
 * the part that stops being possible.
 */
import { useState } from "react";

import { addTask, dropTask, finishTask } from "../lib/api";
import type { Task } from "../lib/types";

export function Tasks({ token, items, onChange }: {
  token: string;
  items: Task[];
  onChange: (next: Task[]) => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(work: () => Promise<{ tasks: Task[] }>) {
    setBusy(true);
    try {
      onChange((await work()).tasks);
    } catch {
      /* the next board load will tell the truth */
    }
    setBusy(false);
  }

  const overdue = items.filter((t) => t.due && t.due * 1000 < Date.now()).length;

  return (
    <section className="panel bracket panel-wide">
      <div className="vision-top">
        <span className="label">To do</span>
        {overdue > 0 && <span className="chip chip-warn">{overdue} OVERDUE</span>}
      </div>

      <form
        className="task-add"
        onSubmit={(e) => {
          e.preventDefault();
          const value = text.trim();
          if (!value) return;
          setText("");
          run(() => addTask(token, value));
        }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Something to do…"
          aria-label="Add a task"
        />
        <button type="submit" className="chip chip-hot" disabled={busy || !text.trim()}>
          ADD
        </button>
      </form>

      {items.length ? (
        <ul className="tasks">
          {items.map((t) => (
            <li key={t.id} className={t.priority === 2 ? "task-high" : ""}>
              {/* A checkbox, because ticking a thing off should feel like
                  ticking a thing off. */}
              <button
                className="task-tick"
                onClick={() => run(() => finishTask(token, t.id))}
                disabled={busy}
                aria-label={`Finish ${t.text}`}
              >
                ○
              </button>
              <span className="task-text">{t.text}</span>
              {t.due ? (
                <span className={`task-when mono${
                  t.due * 1000 < Date.now() ? " task-late" : ""}`}>
                  {new Date(t.due * 1000).toLocaleDateString([], {
                    day: "numeric", month: "short" })}
                </span>
              ) : <span />}
              <button
                className="linkish label"
                onClick={() => run(() => dropTask(token, t.id))}
                disabled={busy}
                aria-label={`Remove ${t.text}`}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted small">
          Nothing on the list. Say &ldquo;I need to write the methodology&rdquo;
          and it will be here.
        </p>
      )}
    </section>
  );
}
