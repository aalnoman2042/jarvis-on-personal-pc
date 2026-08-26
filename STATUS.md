# VONDO — where things stand

Jarvis, v2. Live in the cloud, reachable from anywhere, free.
Architecture and the rules that are easy to break: **[CLAUDE.md](CLAUDE.md)**.

> **The PIN is not in this file.** It is committed to a public repo. The PIN and
> the tokens live in `SECRETS.local.md`, which is gitignored and stays on your
> machine.

---

## Live

| | |
|---|---|
| **The HUD** | https://vondo-core.onrender.com |
| **Health** | https://vondo-core.onrender.com/health |
| **Repo branch** | `v2/phase-00-core-split` — Render redeploys on every push |

### The Android app

Built by GitHub Actions on every push — nothing to install on this PC.

1. **github.com/aalnoman2042/jarvis-on-personal-pc/actions** → newest
   *android apk* run → **Artifacts** → `jarvis-apk`
2. Unzip, open the `.apk` on the phone, allow installing from this source
3. Sign in with the PIN

**You should only ever need to do that once.** The app loads its screens from
the cloud core rather than carrying its own copy, so `git push` updates the app
as well as the server — reopen it and the change is there. A new APK is only
needed when something *native* changes: a new Capacitor plugin, the icon, the
app name, or permissions.

It still opens with no signal. The first launch needs a connection; after that
the service worker has the shell cached. If the cloud is unreachable on a cold
start you get Jarvis's own "no link to the core" screen rather than the
WebView's browser error.

### Or in a browser

1. Open the URL in Chrome.
2. Type your 4-digit PIN on the keypad. It already knows you and your 62
   previous exchanges.
3. **⋮ → Add to Home Screen.** It installs as a real app: own icon, no address
   bar, opens with no signal.

The PIN is typed once per device and then exchanged for a long-lived token, so
it never travels again. Five wrong tries locks that address out for fifteen
minutes — per address, never globally, so nobody can lock you out by guessing
badly on purpose.

**Four digits is 10,000 combinations on a public URL.** The lockout is what
makes that survivable: about three weeks of continuous guessing from one
address. Six digits would multiply that by a hundred for two extra keypresses —
change `VONDO_PIN` in the Render dashboard and it takes effect on restart.

### Linking this PC back in

```bat
set VONDO_URL=https://vondo-core.onrender.com
link_pc.bat        :: once — type your PIN
start_agent.bat    :: leave it running
```

Without the agent, everything works except the things that need the desktop —
opening apps, volume, screenshots, CPU, power.

---

## What it runs on

| Piece | Where | Notes |
|---|---|---|
| Cloud core | Render, Singapore | Free. Sleeps after 15 min idle, ~1 min to wake. A GitHub Actions ping every 10 min keeps it up. |
| Database | Turso, Mumbai | SQLite over HTTPS, ~59 ms. Free: 5 GB, 500M reads/month. Conversation, facts, devices, action log. |
| Brain | Groq · `openai/gpt-oss-120b` | Free tier. Gemini backs it up; the rule-based brain is the last resort. |
| HUD | Served by the core | One origin — no CORS, and the token never crosses a boundary. The Android app loads from here too, so pushing updates it. |
| This PC | The agent only | Four dependencies. No AI, no models, no speech, no window. |

Built weight: 157 kB JS, 8 kB CSS, 155 kB of self-hosted fonts.

---

## Build progress

| Phase | State | What it gave you |
|---|---|---|
| 00 · Restructure | done | `core/` deploys, `legacy/` is v1 and still runs |
| 01 · Memory | done | SQLite + full-text search; 62 exchanges carried over, old files frozen |
| 02 · Cloud API | done | PIN login, chat, websockets, rate limits — 39 checks |
| 03 · PC agent | done | Outbound link, allow-list, local confirm dialog, telemetry — 16 checks |
| 04 · HUD | done | Canvas arc reactor, telemetry gutter, conversation log — 15 checks |
| 05 · Installable | done | Home-screen install, offline open, offline queue, own fonts |
| 05b · Diary | done | Dates parsed from speech, stored, delivered — on the phone even with the app shut. 45 checks |
| 10 · The board | done | Dashboard home, chat behind a floating button, live gauges |
| 08 · Android app | done | Capacitor APK built in CI. Real app, real icon, no SDK on this PC. |
| 09 · Settings | done | Brain, memory, facts, PC, devices — all behind a gear, off the main screen. |
| 06 · Voice | next | Chrome/Android does speech natively; `whisper-large-v3-turbo` is on the Groq key as fallback |
| 07 · Deploy | **live** | Brought forward — phases 05 and 06 cannot be tested on a phone without HTTPS |

---

## Commands

```bat
:: on this PC
start_agent.bat                     :: link this PC to the cloud
python legacy/vondo.py              :: the old v1 desktop assistant
start_jarvis.bat                    :: v1 with its window

:: development
python -m uvicorn server.app:app --reload --port 8000
cd web && npm run dev               :: HUD with hot reload, proxies to :8000
cd web && npm run build             :: build it; the core serves it at /

:: tests — all passing
python tests/test_server.py         :: 39 checks, real server, real sockets
python tests/test_agent.py          :: 16 checks, real agent, real PC action
python tests/test_hud.py            :: 15 checks, built, served, assets resolve
python tests/test_reminders.py      :: 45 checks, dates, storage, delivery

:: deploying
git push                            :: that is the whole deploy
```

---

## What works today

Ask it anything — it is a chatbot with your whole history behind it.

**It remembers.** *"remember today my dad told me to go shopping"* is stored as a
fact and recalled in later conversations, on any device. Verified live.

**It knows you.** 82 exchanges and every fact carry across the phone, the browser
and the app, because they all talk to the same cloud brain.

**It keeps a diary.** *"I have a physics exam on the 18th, warn me the day
before"* is stored with a real date, read straight back to you as Jarvis
understood it, and shown on the board under **Up next**. Verified live.

Reminders reach you three ways, and the phone one is the one that matters:

| Where | How | Works when |
|---|---|---|
| The app, open | pushed down the websocket | you are looking at it |
| The phone, shut | the phone's own alarm clock | app closed, phone offline, server asleep |
| This PC | spoken aloud by the v1 desktop app | it is running |

A reminder that comes due with nothing listening is **not** thrown away — it
waits and arrives the moment you open the app.

### Connecting your mailboxes

Jarvis reads mail over IMAP with an **app password** — not OAuth, which for an
unverified personal app expires every seven days. One string per mailbox, never
expires, works with Gmail and everything else.

For each account:

1. Turn on 2-step verification on the account.
2. Generate an **app password** (Gmail: myaccount.google.com → Security → App
   passwords). It is 16 characters.
3. In the Render dashboard, add an environment variable:

```
VONDO_MAIL_1 = Personal|imap.gmail.com|993|you@gmail.com|abcdefghijklmnop
VONDO_MAIL_2 = University|imap.gmail.com|993|you@uni.edu|qrstuvwxyzabcdef
```

Up to `VONDO_MAIL_9`. The port may be left out; 993 is assumed.

**It can only read.** The IMAP session is opened `readonly=True` and every fetch
uses `BODY.PEEK`, which is the form that does not mark mail as seen — so Jarvis
deciding whether something matters cannot change your inbox. There is no code
path that sends, deletes, moves or flags anything. No message body is stored;
mail is read, ranked, shown and forgotten.

**Treat an app password like the mailbox key it is.** It goes in Render's
environment, never in the repo. If one leaks, revoke it from the same page you
made it on.

**It uses the phone when the PC is asleep.** *"Open YouTube"*, *"call dad"*,
*"message Rifat on WhatsApp"*, *"navigate to CUET"* — the desktop still wins
when it is awake, and the phone catches it when it is not. Calls and messages
are opened ready, never sent: the last tap stays with you. Reading the PC's CPU
still says it is offline, because there is no second answer to that one.

**The board is the home screen.** Opening the app shows what is coming up, your
PC's CPU and memory, how much is remembered and which brain is answering.
Talking to it is the button in the corner.

**Settings** (the gear) shows which brain answered, what it remembers about you
with a way to forget any of it, your PC's CPU, recent actions and signed-in
devices.

---

## Known gaps

**It sleeps unless pinged.** Free Render spins down after 15 minutes without
traffic. The PC agent's telemetry counts as traffic, so it stays awake while
this PC is on; `.github/workflows/keepalive.yml` covers the rest by hitting
`/tick`, which wakes it and sweeps the diary in one call. If that ping
lapses, the first message after a quiet evening waits about a minute. Roughly
$2/month on Fly removes this entirely.

**Installing a new APK may need the old one uninstalled first.** Debug builds
were signed with a key regenerated on every CI run, and Android refuses to
install over an app signed with a different key — so updates failed with "App
not installed" and the phone kept the first APK it ever got. The key is cached
now, so installs are real updates; but getting off any APK built before that fix
needs one clean uninstall.

**A native change still needs a new APK.** Screens update themselves; plugins,
permissions, the icon and the app name do not. Nothing about that is automatic —
if I add a plugin, I have to tell you to reinstall.

**The phone only knows about a reminder it has seen.** Alarms are scheduled on
the device, which means the app has to have been opened at least once between
setting the reminder and it coming due — and notifications have to be allowed.
Set something from the browser on this PC and never open the phone before the
day, and the phone stays quiet; the reminder is still safe in the cloud and
appears the moment you do open it. Closing that properly is real push, which
means Firebase.

**It can see a still picture, not a live screen.** Show it something — point
the camera or pick an image on the **Vision** panel — and Gemini reads the text
and describes what is there. It does *not* identify people: that needs a
database of faces nobody has. Watching a live phone screen is still impossible
from a web app (`getDisplayMedia` is desktop-only), and that has not changed;
the still-image version is the real, buildable one, and it is built.

**Gemini's tool calls are unlogged.** The action log wraps the dispatch table,
which covers Groq, Ollama and Claude. Gemini hands its callables to a schema
generator that inspects them, and wrapping those risks emitting broken schemas.
Only matters when Groq is down.

---

## Traps already paid for

**Groq retires models.** `llama-3.3-70b-versatile` started returning 404 in Aug
2026. The fallback chain worked perfectly and dropped to the rule brain — so
Jarvis kept answering, just stupidly: *"who am I to you"* came back as *"your PC
is offline, so I can't web search"*. When it sounds dim, check the models
endpoint first:

```bash
curl -H "Authorization: Bearer $GROQ_API_KEY" https://api.groq.com/openai/v1/models
```

**`PROJECT_DIR` is derived from `__file__`.** Moving `config.py` into `core/`
would silently repoint `.env` and both memory files inside `core/`. Nothing
raises. It reads exactly like Jarvis forgetting everything.

**PC routing sits in `core/lazy.py`, not the tool dispatcher.** The rule-based
brain calls `actions.*` directly and bypasses the dispatcher entirely — and it
is the brain most likely to be answering when everything else has failed.

**`reactorEngine.ts`, not `reactor.ts`.** It sat beside `Reactor.tsx`, differing
only in casing. Windows resolves that ambiguously; Linux does not.

**Kill the agent and the socket stays half-open**, so the cloud still thinks the
PC is listening and "open chrome" waits out a timeout instead of saying it is
asleep. `request_stop()` closes it properly.

**`core.memory.facts` is a function, not the submodule** — the package
re-export shadows it. Reach the module with `importlib.import_module`.

**`height: 100%` and `100vh` do not shrink for a keyboard.** On Android the
keyboard is drawn over the window rather than resizing it, so a full-height
layout keeps believing it has a whole screen and the composer ends up behind the
keyboard — you tap the box and it disappears. `web/src/lib/viewport.ts` reads
`visualViewport` into `--app-height`. Anything full-height added later uses that
variable, not the units.

**A phone grid with `auto` rows pushes its own footer off-screen.** The log grows
with every message; `1fr auto` is what pins whatever sits under it.

**Adding a column to an existing table needs `_LATER_COLUMNS` in `store.py`.**
`CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists, so the
schema string and the live database drift apart — and only the deployed copy
finds out.
