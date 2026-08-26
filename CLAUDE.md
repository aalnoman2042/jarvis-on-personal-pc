# VONDO — working notes

Jarvis: a personal assistant for Rohan. v1 was a Windows desktop app; v2 moves
the brain to the cloud and puts a HUD on every screen. Both live in this repo
during the migration.

## Where things are

| Folder | What it is | May it touch Windows? |
|---|---|---|
| `core/` | Brains, memory, tools, settings. Deploys to the cloud. | **No** (one exception below) |
| `legacy/` | v1: console loop, Tkinter window, local mic/speakers. Still works. | Yes |
| `requirements/` | Three dependency lists: `cloud`, `agent`, `legacy`. | — |
| `server/` | FastAPI cloud core. **Phase 02.** | No |
| `agent/` | The thin PC agent. **Phase 03.** | Yes — that's its job |
| `web/` | The React PWA / FUI. **Phase 04.** | — |

`.bat` launchers stay at the repo root because Rohan double-clicks them.

## Rules that are easy to break

**`core/` must import cleanly on Linux with no mic, no screen, no Windows.**
That is the whole point of the split — it is what gets deployed.

**The one exception is `core/actions.py`**, which still holds the Windows half of
the tool set (`pyautogui`, `psutil`, `ctypes`, `taskkill`). It is split into the
PC agent in phase 03. Until then it is imported *lazily* by `core/tools/llm_tools.py`
and never at package-import time. Do not add new Windows code to `core/`.

**`PROJECT_DIR` is the repo root, not the folder the module sits in.** Both
`core/config.py` and `core/actions.py` walk up one level from `__file__`:

```python
CORE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CORE_DIR)          # <- the extra dirname matters
```

Collapse that and `.env`, `jarvis.state`, `jarvis.history.jsonl` and
`jarvis.facts.json` all silently resolve inside `core/`. Nothing raises. Jarvis
just boots with no API keys and no memory, which reads as "it forgot everything".

**Legacy scripts are run directly, not imported.** `legacy/` is deliberately not
a package. Each entry point carries a small bootstrap that puts the repo root on
`sys.path` so `core` resolves; sibling imports (`from voice import Voice`,
`import vondo`) work because Python already put `legacy/` on the path.

**Brains are imported lazily, never in `core/brains/__init__.py`.** Importing
them all would drag in every provider SDK, and one missing optional package
would break the entire core.

## Memory

`core/memory/` is a package: `store.py` (SQLite), `facts.py` (the notes Jarvis
keeps about Rohan), `migrate.py` (the one-time import from v1's files), and
`__init__.py` as the public face. **Callers must go through `__init__`** —
`memory.add_turn(...)`, `memory.wrap(brain)`, `memory.as_openai(...)`. That
indirection is what let flat files become SQLite without touching a brain.

- The database is `vondo.db` at the repo root, `VONDO_DB` overrides the path
  (that is how the cloud core will point at its mounted volume). Gitignored.
- WAL mode, one connection per thread — there is a reminder thread, a UI thread
  and soon a websocket loop, and sqlite3 connections are not thread-safe.
- **Nothing in the package may raise into a conversation.** Every public function
  swallows storage errors and degrades to "nothing remembered", exactly as the
  file version did. Memory failing is annoying; memory taking Jarvis down is not.
- **Retention is forever; context is trimmed.** Storage keeps everything (a few
  MB for years). `as_openai` decides how much a model sees this turn. These are
  different decisions — do not conflate them again.
- `jarvis.history.jsonl` and `jarvis.facts.json` are **frozen, not deleted**.
  Nothing writes to them. They are the way back if the database disappoints.
  A marker row in `meta` makes the import run exactly once.
- Still text only, never tool-call scaffolding — see the note in `__init__`.

**Known gap:** the action log is written by wrapping `DISPATCH` in
`core/tools/llm_tools.py`, which covers Groq, Ollama and Claude. Gemini calls
`TOOL_FUNCTIONS` directly and its schema generator introspects each callable, so
wrapping those risks emitting `(*args, **kwargs)` schemas. Gemini's tool calls
are therefore unlogged; close it inside the Gemini brain's own call path.

## The cloud core (phase 02)

`server/` is FastAPI in front of the same brains, memory and tools. `app.py`
(routes), `auth.py` (pairing and tokens), `agents.py` (the link to the PC).

```
python -m uvicorn server.app:app --reload --port 8000
python tests/test_server.py      # 34 checks, real server, real sockets, temp DB
```

**Brains block, so every turn runs in a worker thread** (`run_in_threadpool`)
behind an `asyncio.Lock`. Calling a brain directly in an async endpoint would
freeze the event loop — including the websocket carrying the PC agent. The lock
also matches what the single shared conversation history already assumes.

**PC routing lives in `core/lazy.py`, not in the tool dispatcher.** This matters:
the AI brains reach the desktop through `llm_tools.DISPATCH`, but the rule-based
`FreeBrain` calls `actions.open_app(...)` directly. Hooking the dispatcher alone
covered the AI brains and silently missed the offline one — the brain most
likely to be answering when everything else has failed. `core.lazy` sits under
both and cannot be bypassed. `PC_FUNCTIONS` there is the single list of what
needs the desktop; do not keep a second copy anywhere.

**A missing PC is answered, not waited for.** No agent connected means an
immediate spoken sentence, never a hung conversation. Rohan chose that.

**Signing in is a four-digit PIN**, and the PIN is the whole story — there is no
pairing flow any more. It is typed once per device and exchanged for a
long-lived token; tokens are stored as hashes only.

Four digits is 10,000 combinations on a public URL, so the throttle is not
optional: five wrong tries locks that **address** for fifteen minutes, and every
attempt pays a fixed delay whether it is right or wrong (a delay only on failure
tells an attacker which guesses were warm). The lockout must stay per-address —
a global one lets anyone lock Rohan out by guessing badly on purpose. Behind a
proxy that means reading the forwarded address, or every visitor shares one
bucket.

**"Streaming" is events, not tokens.** Brains return finished strings today, so
the websocket reports status (`thinking`) and then one `reply`. The frame format
already has a `token` type so real streaming needs no protocol change. Do not
fake it by chunking a finished string.

## The PC agent (phase 03)

`agent/` is the only VONDO process on Rohan's machine and must stay small:
`agent.py` (the loop), `guard.py` (what it will do), `pair.py` (one-time setup),
`settings.py`. Four dependencies, no AI, no models, no speech, no window. If
something here starts needing a heavyweight package, the work belongs in the
cloud instead.

```
link_pc.bat        # once — type your PIN
start_agent.bat    # run it
python tests/test_agent.py    # 17 checks, real agent, real server, temp everything
```

**The allow-list is imported, never retyped.** `guard.ALLOWED` *is*
`core.lazy.PC_FUNCTIONS`. Two copies drift into "the server can ask for
something the agent forgot about". It is an allow-list on purpose: a block-list
would have to anticipate every dangerous thing, this has to anticipate nothing.

**Destructive actions ask again, here.** Shutdown, restart and force-closing a
named app pop a `MessageBoxTimeoutW` on the desk (30s, "No" focused, timeout
means no). The cloud's confirm gate is code on a server; if that server were
compromised it is exactly as trustworthy as the thing that failed. Closing the
*front* window is exempt — that is a polite WM_CLOSE and still prompts to save.
If `MessageBoxTimeoutW` were ever missing we refuse rather than risk a dialog
that hangs forever on an unattended machine.

**Stopping cleanly is a feature, not tidiness.** `request_stop()` closes the
websocket so the cloud marks the PC offline *at once*. Killing the process
leaves the socket half-open, and until TCP notices, "open chrome" from the phone
waits out a timeout instead of saying the PC is asleep. The reconnect backoff
waits on the stop event too, or quitting during a 60-second backoff hangs.

**The token lives in `agent.token`, not `.env`.** `.env` is the file Rohan
opens, edits and occasionally screenshots. A long-lived credential does not
belong in the middle of that. Gitignored; `VONDO_AGENT_TOKEN_FILE` overrides it
for tests.

## The diary (phase 05)

`core/clock.py` reads a date out of a phrase, `core/memory/agenda.py` stores it,
`core/reminders.py` announces it on the desktop, `server/nudges.py` delivers it
in the cloud, `web/src/lib/notify.ts` mirrors it onto the phone.

```
python tests/test_reminders.py    # 45 checks, real server, real socket, temp DB
```

**Parsing happens in Python, not in the model.** Asking a brain for an ISO
timestamp is tempting and unreliable — it invents the year, forgets the
timezone, and the rule-based brain cannot do it at all. The `remind` tool takes
the phrase Rohan actually said and `clock.parse_when` turns it into an epoch, so
every brain gets the same dates for free.

**Dates are built in Rohan's timezone and stored as epochs.** The core runs in
UTC in Singapore; "18 September" means the 18th in Dhaka. `VONDO_TZ` names the
zone, `VONDO_UTC_OFFSET` is the fallback for platforms with no tz database
(Windows). Getting this wrong shifts every reminder by six hours.

**`due` and `remind_at` are different columns on purpose.** An exam warning
delivered as the invigilator hands out papers is not a warning. `all_day` is a
third: "18 September" names no hour, and inventing nine in the morning and
reading it back confidently is how you stop trusting the thing.

**A reminder is marked delivered only if somebody was actually told.** The
sweeper broadcasts to open sockets and marks `fired` per successful send. A free
tier waking at some arbitrary moment with nobody connected must not consume the
exam warning and go back to sleep — it waits, and arrives when the app opens.
`test_reminders.py` section 8 is exactly this regression. The desktop's
`sweep()` still marks immediately, because speaking out loud *is* delivery.

**Phones schedule their own alarms.** `notify.ts` mirrors the diary into
Capacitor local notifications, so the OS fires them with the app closed, the
phone offline and the server asleep. Push was the obvious answer and the wrong
one: the APK is a WebView, where the Web Push API does not exist, and the native
route is Firebase — an account, a project, and a Google dependency in something
that deliberately has none. The cloud stays the source of truth; the phone keeps
a cache with a clock.

**`/tick` is unauthenticated and must stay harmless.** No arguments, no output
but counts, and it does exactly what the server does by itself every thirty
seconds. It exists because a sleeping instance has no timers.

**Adding a column to `reminders` needs `_LATER_COLUMNS` in `store.py`.**
`CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists, so the
schema string and a live database drift apart silently — and the drift only
shows up on the deployed copy.

## The HUD (phase 04)

`web/` is Vite + React + TypeScript, built to `web/dist` and served by the cloud
core at `/`. One origin, so no CORS and the token never crosses an origin.

**Home is the board, not the conversation.** `screens/Dashboard.tsx` — what is
coming up, the PC's gauges, what is remembered, which brain is answering.
Chat is `hud/ChatSheet.tsx`, a full-screen drawer behind the floating button;
settings is a second drawer behind the gear. The socket is held by `App.tsx`
above all three, so opening or closing a drawer never drops the connection or
loses the log.

**Nothing on the board is estimated.** A reading that has not arrived draws as a
dash, never as zero — zero is a reading and nothing is not, and an invented
figure rendered as a precise gauge makes the true numbers beside it
untrustworthy. If a panel would need data nothing collects, the panel does not
exist yet.

```
cd web && npm run build          # then the core serves it at /
cd web && npm run dev            # port 5173, proxies the API to :8000
python tests/test_hud.py         # 15 checks: built, served, assets resolve
start_hud.bat                    # its own window, no address bar
```

**The reactor runs outside React.** `hud/reactorEngine.ts` owns a canvas and one
`requestAnimationFrame` loop; `hud/Reactor.tsx` only owns the element's
lifetime. State and mic level reach the loop through a mutable ref, not props —
passing them as props would tear down and restart the animation every time
Jarvis started thinking, and the rings would snap back to zero.

Three rules the loop keeps, because "lightweight" was a stated requirement:
one canvas and one frame (not a frame per ring); nothing at all while the tab is
hidden; and idle motion slow enough to read as switched-on from the corner of
your eye without pulling it, since this may sit on a second monitor.

**Everything is a token in `theme.css`.** No hex values in components — that is
what makes the KAREN palette a second `[data-theme]` block rather than a rewrite.

**`reactorEngine.ts`, not `reactor.ts`.** It sat beside `Reactor.tsx` and the two
differed only in casing, which Windows resolves ambiguously and Linux resolves
differently — a bug that would only have appeared on Fly.

**The shell is sized from `visualViewport`, not `100%` or `100vh`.** Both of
those measure the *window*, and on Android the window does not shrink when the
keyboard opens — it is drawn over the top. `lib/viewport.ts` puts the real
height in `--app-height` and a `keyboard-up` class on `<html>`. Without it the
composer sits behind the keyboard: you tap the box and it disappears. Any
full-height layout added later must use the variable.

Keyboard detection compares against the tallest viewport ever seen, not against
`window.innerHeight`: the manifest asks for `adjustResize`, so the window
shrinks along with the viewport and the difference between them is always zero.

**Grid rows on a phone must be explicit.** Left on `auto`, a log grows with
every message until it pushes whatever is below it off the bottom of the screen.
`1fr auto` in `.chat-sheet` is what pins the composer.

**Watch the mount order in `app.py`.** `StaticFiles` is mounted at `/` and must
stay last; anywhere earlier it swallows `/chat` and `/health`. `test_hud.py`
checks exactly that.

**Fonts come from Google Fonts today**, with real fallback stacks. Phase 05 must
self-host them, or an installed app with no signal loses its typography.

**Two traps in `core/memory`, both of which have already bitten:**

`core.memory.facts` resolves to a *function*, not the submodule — `__init__.py`
re-exports `facts = _facts_mod.facts`, which shadows the module of the same
name on the package. Inside the package `from core.memory import facts` still
gets the module (the rebind happens after), but from outside it does not. Reach
the module with `importlib.import_module("core.memory.facts")`.

The Turso client runs a background thread, so a **script** that opens a
connection and never closes it hangs at exit instead of finishing. Call
`conn.close()` in anything short-lived. The server is unaffected — it holds the
connection for its lifetime by design.

## Imports after the phase-00 move

| Was | Now |
|---|---|
| `import config` | `from core import config` |
| `import memory` / `confirm` / `reminders` / `actions` | `from core import ...` |
| `import llm_tools` | `from core.tools import llm_tools` |
| `from brain_groq import GroqBrain` | `from core.brains.brain_groq import GroqBrain` |

## Running it

```
python legacy/vondo.py        # v1 console assistant
start_jarvis.bat              # v1 window (pythonw, no console)
setup.bat                     # venv + requirements/legacy.txt
enable_autostart.bat          # regenerates the Startup .vbs
```

Autostart writes `%APPDATA%\...\Startup\Jarvis.vbs` with **absolute paths baked
in**. Move `legacy/jarvis_gui.py` and that file goes stale silently — rerun
`enable_autostart.bat` after any such move. It also reads `jarvis.state` first
and quits if Jarvis was powered off last time.

## Settled decisions — do not reopen

Cloud core on **Fly.io**; **web PWA** for desktop and Android; **device pairing**
with revocable per-device tokens; **SQLite** on a persistent volume; **browser
speech** with Groq Whisper as fallback; **Iron Man HUD** built on theme tokens.
Free tiers throughout, with Claude as a one-variable paid toggle.

The local Ollama model was deleted on 2026-08-26 — it had never actually been
installed, so `brain_ollama` was failing silently and the fallback chain was
stepping over it. The code stays; the model does not come back unless asked.

## Gotchas inherited from v1

- Groq's llama-3.3 sometimes malforms no-arg tool calls; `brain_groq.py` handles
  it with rollback + retry. Don't "simplify" that away.
- `memory.py` stores plain user/assistant text only, never tool-call scaffolding —
  providers shape tool calls incompatibly, and a trimmed history that orphans a
  tool result from its call gets rejected outright.
- `brain_fallback.py` puts a failed brain on a 30-minute cooldown. Without it,
  every question re-pays a dead brain's timeout (13s vs 0.8s).
- The mic is a DroidCam phone with a noise floor near 18, so `Voice.MIN_ENERGY`
  is floored at 120. STT uses `en-IN`.
