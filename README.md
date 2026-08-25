# JARVIS / VONDO — a voice assistant for your PC

> **This README describes v1, the Windows desktop app.** It still works and is
> still supported — everything below runs, with one change: the Python files now
> live in `core/` and `legacy/`, so the console version starts with
> `python legacy/vondo.py`. The `.bat` launchers are unchanged; double-click them
> as before.
>
> **Two sections are now out of date.** The offline Ollama brain was removed on
> 26 Aug 2026 (it had never actually been installed, so it had never worked), and
> `requirements.txt` is now three files under `requirements/`. Ignore the Ollama
> instructions and the "fully offline" claim until this page is rewritten.
>
> v2 moves the brain to the cloud and replaces this window with a HUD that runs
> on desktop and phone. Architecture and build order: **[CLAUDE.md](CLAUDE.md)**.

Speak to your computer and it answers out loud and actually does things — opens
apps, searches the web, sets reminders, checks your CPU, locks the screen, shuts
down. It runs **100% free** and installs on any Windows PC in about five minutes.

```
    ┌─────────────────────────────┐
    │          JARVIS             │
    │            ◉                │      "Jarvis, open Chrome"
    │        Listening            │   →  "Opening chrome."
    │  Brain [Ollama · offline ▾] │
    │                             │
    │  You:     what's my cpu     │
    │  Jarvis:  CPU is at 12      │
    │           percent, memory   │
    │           at 41 percent     │
    └─────────────────────────────┘
```

---

## Table of contents

1. [Quick start](#quick-start)
2. [What it can do](#what-it-can-do)
3. [The five brains](#the-five-brains)
4. [Offline AI — no key, no internet](#offline-ai--no-key-no-internet)
5. [Install on any computer](#install-on-any-computer)
6. [Everyday use](#everyday-use)
7. [Start automatically with your PC](#start-automatically-with-your-pc)
8. [Every setting explained](#every-setting-explained)
9. [Voice commands cheat sheet](#voice-commands-cheat-sheet)
10. [Troubleshooting](#troubleshooting)
11. [How it works](#how-it-works)
12. [File map](#file-map)
13. [Privacy](#privacy)

---

## Quick start

**On a brand-new PC, in order:**

| # | Do this | Why |
|---|---------|-----|
| 1 | Install [Python 3.10+](https://python.org/downloads) — **tick "Add Python to PATH"** | The only prerequisite |
| 2 | Get the folder (`git clone` or copy from USB) | The app itself |
| 3 | Double-click **`setup.bat`** | Builds everything, asks for your key |
| 4 | Double-click **`start_jarvis.bat`** | Jarvis comes online |

That's it. Say **"Jarvis, what time is it?"**

---

## What it can do

### 🎙️ Voice in, voice out
Listens through your mic, thinks, and speaks the answer back. No typing.

### 🚀 Open and close things
- "Jarvis, **open Chrome**" · "open Notepad" · "open Spotify" · "open VS Code"
- "Jarvis, **close Chrome**" · "quit Spotify"
- "Jarvis, **open YouTube**" · "open github.com" · "go to Gmail"

### 🔎 Search and look things up
- "Jarvis, **search for** the weather in Dhaka"
- "Jarvis, **Wikipedia** black holes"
- Ask anything at all — with an AI brain it just answers you conversationally.

### ⏰ Reminders and timers
- "Jarvis, **remind me in 10 minutes to** take the rice off"
- "Jarvis, set a timer for 30 seconds"

Reminders run in the background and Jarvis **speaks them out loud** when due.

### 🖥️ System control
- "Jarvis, **how's my PC?**" → CPU, memory, and battery in one spoken line
- "Jarvis, **volume up / down / mute**"
- "Jarvis, **play** / **pause** / **next track**"
- "Jarvis, **take a screenshot**" → saved to your Pictures folder
- "Jarvis, **lock the screen**"
- "Jarvis, **shut down**" / "restart" → 30-second delay, say **"cancel"** to stop it

### 🧠 Swap AI brains mid-conversation
A dropdown in the window switches between free cloud AI, **offline local AI**, and
paid Claude — instantly, no restart. Your pick is remembered next time.

### 🛡️ Never breaks
If your API key runs out, the internet drops, or a service rate-limits you,
Jarvis **silently falls back** to the built-in offline rule engine and keeps
working. It does not crash and it does not go silent.

### 🔌 Starts with your PC
Optional auto-start that greets you at boot — and remembers if you turned it off,
so it stays off until you want it back.

---

## The five brains

Every brain uses the same voice and the same PC controls. Only the intelligence
differs. **Switch any time from the `Brain` dropdown in the window.**

| Brain | Cost | Needs | Internet? | Best for |
|-------|------|-------|-----------|----------|
| **Gemini** *(default)* | **Free** | Free Google key | Yes | Best all-round free quality |
| **Groq** | **Free** | Free Groq key | Yes | Fastest replies of any option |
| **Ollama** | **Free** | One 2 GB download | **No** | Privacy, no keys, no limits |
| **Claude** | Paid | Anthropic key | Yes | Smartest, best at complex requests |
| **Offline rules** | **Free** | Nothing | No | Guaranteed fallback, zero setup |

**Get a free key:**
- Gemini → https://aistudio.google.com/app/apikey
- Groq → https://console.groq.com/keys

You only need **one**. Paste it into `.env` and you're done.

> **Why "offline rules" exists:** it matches keywords instead of understanding
> language, so it's less clever — but it needs nothing at all and never fails.
> It's the safety net every other brain falls back to.

---

## Offline AI — no key, no internet

Run **`install_local_llm.bat`** once. It:

1. Downloads Ollama (~700 MB) into the project's `local llm` folder
2. Downloads the AI model (~2 GB) into `local llm\models`
3. Points everything at that folder — **nothing touches your C: drive**

Then open Jarvis and pick **Ollama** in the Brain dropdown. From that moment
nothing you say leaves your computer, there are no API keys, no daily limits,
and it works with the Wi-Fi off.

### Choosing a model

On a normal CPU-only PC (no gaming GPU):

| Model | Size | Speed | Controls your PC? |
|-------|------|-------|-------------------|
| **`qwen2.5:3b`** ← default | 1.9 GB | Snappy, feels instant | ✅ Yes |
| `llama3.2:3b` | 2.0 GB | Same speed, chattier tone | ✅ Yes |
| `qwen2.5:7b` | 4.7 GB | Smarter, but a 3–4s pause | ✅ Yes |
| ~~`phi3:mini`~~ | 2.2 GB | Fast | ❌ **No — chat only** |

> ⚠️ **Avoid phi3 and other sub-3B models.** They can't do *tool calling*, which
> is the mechanism that lets Jarvis actually open Chrome or set a reminder. They
> will happily chat and then do nothing.

To change model:
```powershell
"local llm\ollama\ollama.exe" pull llama3.2:3b
```
then set `OLLAMA_MODEL=llama3.2:3b` in `.env`.

**Got a real GPU?** (NVIDIA, 8 GB+ VRAM) Ollama uses it automatically — jump
straight to `qwen2.5:7b`, it'll be faster than the 3b is on CPU.

---

## Install on any computer

### Option A — clone from GitHub (recommended)

```powershell
git clone https://github.com/aalnoman2042/jarvis-on-personal-pc.git jarvis
cd jarvis
.\setup.bat
```

### Option B — copy the folder (USB stick, network drive)

Copy the whole folder, then double-click `setup.bat`. Skip `.venv` and
`local llm` when copying — `setup.bat` rebuilds them, and they're huge.

### What `setup.bat` does for you

- ✅ Checks Python is installed and new enough
- ✅ Builds a **private `.venv` inside the folder** — nothing installed system-wide, no conflicts with other Python projects
- ✅ Installs all dependencies, with an automatic **PyAudio fallback** (the one package that commonly fails on fresh Windows)
- ✅ Creates your `.env` from the template and opens it for your key
- ✅ Tells you exactly what to run next

Run it as many times as you like — it's safe to re-run and won't overwrite your
settings.

### Pushing your changes back to GitHub

```powershell
git add -A
git commit -m "what you changed"
git push
```

Your `.env` is in `.gitignore`, so **your API keys are never uploaded.** The
`local llm` folder and `.venv` are ignored too, so the repo stays small.

---

## Everyday use

### Starting it

| File | What you get |
|------|--------------|
| **`start_jarvis.bat`** | The window UI — orb, live transcript, brain dropdown. **Use this one.** |
| `run.bat` | Console version — ugly, but shows every error. Use when troubleshooting. |
| `stop_jarvis.bat` | Force-stops Jarvis if it's stuck |

### The window

- **The orb** pulses green while listening, amber while thinking, blue while speaking
- **The transcript** shows what it heard and what it said
- **Brain dropdown** — switch AI backends live
- **⏸ Pause** — stop listening without quitting (Jarvis ignores you until resumed)
- **⏻ Power Off** — full stop, *and* it stays off at next boot until you start it again

### Talking to it

By default Jarvis waits for its **wake word**:

> "**Jarvis**, open Chrome" · "**Jarvis**, what's the CPU usage?" · "**Jarvis**, remind me in 5 minutes to stretch"

You can also just say "**Jarvis**", wait for it to answer "Yes?", then speak your command.

Say **"goodbye"** to shut it down by voice.

**Hate the wake word?** Set `LISTEN_MODE=continuous` in `.env` and it responds to
everything it hears. (Great when you're alone; noisy in a shared room.)

The wake word is fuzzy-matched, so common mishearings — "jervis", "javis",
"service" — still trigger it.

---

## Start automatically with your PC

Double-click **`enable_autostart.bat`** once.

From then on Jarvis launches hidden at every login and greets you with
*"Welcome back, sir. System booting."*

It's smart about it: if you hit **⏻ Power Off**, it stays off through the next
reboot too. It only comes back when you start it yourself. To remove auto-start
completely, run **`disable_autostart.bat`**.

You can also do it by voice: *"Jarvis, enable auto start"* / *"disable auto start"*.

---

## Every setting explained

All settings live in **`.env`** (created by `setup.bat` from `.env.example`).
Edit with Notepad, save, restart Jarvis.

### Which brain

```ini
VONDO_BRAIN=gemini      # gemini | groq | ollama | claude | free
```
> You normally don't need to touch this — the dropdown in the window changes it
> for you and writes it back here.

### API keys

```ini
GEMINI_API_KEY=              # https://aistudio.google.com/app/apikey
GEMINI_MODEL=gemini-2.5-flash

GROQ_API_KEY=                # https://console.groq.com/keys
GROQ_MODEL=llama-3.3-70b-versatile

ANTHROPIC_API_KEY=           # https://console.anthropic.com  (paid)
CLAUDE_MODEL=claude-opus-4-8
```

### Local AI

```ini
OLLAMA_MODEL=qwen2.5:3b            # which local model to use
OLLAMA_HOST=http://127.0.0.1:11434 # where the local server lives
OLLAMA_TIMEOUT=120                 # seconds to wait before giving up
```

### Personality

```ini
ASSISTANT_NAME=Jarvis    # what it calls itself
USER_TITLE=sir           # how it addresses you — "sir", "boss", your name, or blank
```

### Listening

```ini
LISTEN_MODE=wake         # wake = needs the wake word | continuous = always listening
WAKE_WORD=jarvis         # rename it to anything
MIC_INDEX=               # blank = Windows default mic. Run list_mics.py to see options
```

### Voice

```ini
TTS_VOICE=               # part of a Windows voice name, e.g. David or Zira. Blank = default
TTS_RATE=175             # words per minute — lower is slower
```
Run **`try_voices.py`** to hear every voice on your PC and pick one.

---

## Voice commands cheat sheet

| Say | It does |
|-----|---------|
| "open chrome / notepad / spotify / calculator" | Launches the app |
| "close chrome" | Kills the app |
| "open youtube / github / gmail / netflix" | Opens the site |
| "open example.com" | Opens any domain |
| "search for cheap flights to Dubai" | Google search in your browser |
| "wikipedia quantum computing" | Opens the Wikipedia page |
| "what time is it" / "what's the date" | Speaks it |
| "how's my pc" / "cpu" / "battery" | CPU, RAM, battery status |
| "remind me in 10 minutes to call mom" | Spoken reminder later |
| "set a timer for 5 minutes" | Same thing |
| "volume up / down / mute" | System volume |
| "play / pause / next track / previous track" | Media keys |
| "take a screenshot" | Saves to Pictures |
| "lock the screen" | Locks Windows |
| "shut down" / "restart" | 30s delay — say **"cancel"** to abort |
| "enable auto start" / "disable auto start" | Boot launch on/off |
| "goodbye" / "go to sleep" | Quits Jarvis |

With an AI brain you don't have to match these phrasings — say it however you
like ("kill chrome would you", "how much RAM am I using") and it understands.

---

## Troubleshooting

**"Python is not installed, or not on your PATH"**
Reinstall Python from python.org and **tick "Add Python to PATH"** on the first
screen. Then re-run `setup.bat`.

**PyAudio fails to install**
`setup.bat` handles this automatically. If it still fails, run manually:
```powershell
.venv\Scripts\python.exe -m pip install pipwin
.venv\Scripts\python.exe -m pipwin install pyaudio
```

**Jarvis can't hear me**
Run **`test_mic.py`** to check the mic, and **`list_mics.py`** to list devices —
then set `MIC_INDEX=` in `.env` to the number of the right one.

**Jarvis has no voice**
Run **`test_speaker.py`**. If it's silent, check your output device in Windows
sound settings.

**It hears me but does nothing**
Say the wake word first ("Jarvis, ..."), or set `LISTEN_MODE=continuous`.

**"the ollama brain wouldn't start"**
The local server isn't running. Re-run `install_local_llm.bat`, or start it
manually:
```powershell
"local llm\ollama\ollama.exe" serve
```

**It answers, but won't open apps (on Ollama)**
Your model can't do tool calling. Switch to `qwen2.5:3b` or `llama3.2:3b`.

**Replies are slow on Ollama**
Use a smaller model (`qwen2.5:3b`), or switch the dropdown to Groq — it's the
fastest cloud option.

**Rate limit errors on Gemini/Groq**
The free tiers have daily caps. Switch brains in the dropdown, or use Ollama
which has no limits at all. Jarvis auto-falls back to offline rules regardless,
so it keeps working either way.

**Seeing errors but the window shows nothing**
Close it and run **`run.bat`** instead — the console prints everything.

---

## How it works

```
   🎤 Microphone
        │
        ▼
   voice.py ──── speech → text (Google's free speech API)
        │
        ▼
   vondo.py ──── wake word check ("Jarvis, ...")
        │
        ▼
   brain_*.py ── understands you, decides what to do
        │              │
        │              └──► llm_tools.py ──► actions.py ──► 🖥️ your PC
        ▼
   voice.py ──── text → speech (offline Windows voice)
        │
        ▼
   🔊 Speaker
```

- **Speech recognition** uses Google's free web API — it needs internet even in
  Ollama mode. (Only the recognition step; your conversation stays local.)
- **Speech output** is fully offline via Windows SAPI5.
- **Every brain calls the same `actions.py`**, so PC control behaves identically
  no matter which one you pick.
- **`brain_fallback.py`** wraps every AI brain — any failure drops to the offline
  rule engine instead of crashing.

---

## File map

Double-click launchers stay at the top level. The Python moved: `core/` is the
portable half that v2 deploys to the cloud, `legacy/` is this desktop app.

| File | Purpose |
|------|---------|
| **`setup.bat`** | **Run first on a new PC** — builds the whole environment |
| `start_jarvis.bat` | Start the window UI |
| `run.bat` | Start the console version (shows errors) |
| `stop_jarvis.bat` | Force-stop Jarvis |
| `enable_autostart.bat` / `disable_autostart.bat` | Boot launch on/off |
| `CLAUDE.md` | How v2 is put together, and what not to break |
| `requirements/cloud.txt` · `agent.txt` · `legacy.txt` | Dependencies, split by where they run |
| `core/config.py` | Reads and writes your `.env` settings |
| `core/memory.py` | The conversation and facts Jarvis remembers |
| `core/actions.py` | Everything it can DO on your PC |
| `core/confirm.py` | Asks before anything it cannot undo |
| `core/reminders.py` | Background reminder timer |
| `core/lazy.py` | Defers the Windows-only imports so `core` runs on Linux too |
| `core/tools/llm_tools.py` | Tool definitions the AI brains call |
| `core/brains/brain_groq.py` | Free cloud brain (fastest) — the current default |
| `core/brains/brain_gemini.py` | Free cloud brain (Google) |
| `core/brains/brain_free.py` | Offline rule-based brain, no AI |
| `core/brains/brain_fallback.py` | Auto-drops to the next brain on any failure |
| `core/brains/brain_claude.py` | Paid brain (Anthropic) |
| `core/brains/brain_ollama.py` | Local offline brain — code kept, model removed |
| `legacy/vondo.py` | Main loop — listen → think → act → speak |
| `legacy/jarvis_gui.py` | The window: orb, transcript, brain dropdown, buttons |
| `legacy/voice.py` | Mic (speech→text) and speaker (text→speech) |
| `legacy/test_mic.py` · `test_speaker.py` · `list_mics.py` · `try_voices.py` | Setup helpers |
| `.env` | **Your settings and keys — never uploaded to GitHub** |

---

## Privacy

- Everything runs **locally on your PC**. There's no server, no account, no telemetry.
- With **Ollama**, your conversation never leaves the machine at all.
- With cloud brains, only the **text of your command** goes to that provider — no
  audio, no files, no screen contents.
- **Speech recognition** sends your spoken audio to Google's free API. That's the
  one step that's always online, in every mode. Swapping it for a local engine
  (Vosk / Whisper) is the obvious next upgrade if you want 100% offline.
- Your API keys live only in `.env`, which is git-ignored and never pushed.

---

## Requirements

- **Windows 10 or 11**
- **Python 3.10+** (3.13 tested)
- A microphone and speakers
- Internet — for speech recognition, and for the cloud brains
- ~3 GB free disk if you use the offline AI brain
