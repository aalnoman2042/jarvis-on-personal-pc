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

### Getting a device in

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
pair_agent.bat     :: once — type your PIN
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
| HUD | Served by the core | One origin — no CORS, and the token never crosses a boundary. |
| This PC | The agent only | Four dependencies. No AI, no models, no speech, no window. |

Built weight: 157 kB JS, 8 kB CSS, 155 kB of self-hosted fonts.

---

## Build progress

| Phase | State | What it gave you |
|---|---|---|
| 00 · Restructure | done | `core/` deploys, `legacy/` is v1 and still runs |
| 01 · Memory | done | SQLite + full-text search; 62 exchanges carried over, old files frozen |
| 02 · Cloud API | done | Pairing, chat, websockets, rate limits — 34 checks |
| 03 · PC agent | done | Outbound link, allow-list, local confirm dialog, telemetry — 17 checks |
| 04 · HUD | done | Canvas arc reactor, telemetry gutter, conversation log — 15 checks |
| 05 · Installable | **most of it** | Home-screen install, offline open, offline queue, own fonts. **Push not sending yet.** |
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
python tests/test_server.py         :: 34 checks, real server, real sockets
python tests/test_agent.py          :: 17 checks, real agent, real PC action
python tests/test_hud.py            :: 15 checks, built, served, assets resolve

:: deploying
git push                            :: that is the whole deploy
```

---

## Known gaps

**Reminders do not fire in the cloud.** Ask for one and nothing happens,
silently. `reminders.start()` needs a speak-callback that only the desktop
provides, so on the server the loop never runs and the reminder vanishes on
restart. Fixed by finishing phase 05 — persist to the `reminders` table and
deliver by web push. **Until then, do not trust a reminder.**

**It sleeps unless pinged.** Free Render spins down after 15 minutes without
traffic. The PC agent's telemetry counts as traffic, so it stays awake while
this PC is on; `.github/workflows/keepalive.yml` covers the rest. If that ping
lapses, the first message after a quiet evening waits about a minute. Roughly
$2/month on Fly removes this entirely.

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
