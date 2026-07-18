# VONDO — voice assistant for your PC

VONDO listens to your voice, talks back, and controls your Windows PC. It starts
**100% free** and upgrades to the paid Claude brain whenever you want — just one
line in a config file.

## What it can do

- **Open apps & files** — "Hey Vondo, open Chrome", "open Notepad", "open Spotify"
- **Web & search** — "open YouTube", "search for the weather in Dhaka", "open github.com"
- **System control** — "volume up", "mute", "take a screenshot", "how's my PC?", "lock the screen", "shut down"
- **Answer questions** — general knowledge and conversation (with the AI brains)

## The five brains — switch any time from the dropdown

| `VONDO_BRAIN` | Cost | Needs | Internet? | Notes |
|---------------|------|-------|-----------|-------|
| `gemini` *(default)* | **Free** | Free Google key | Yes | Natural language + PC control |
| `groq` | **Free** | Free Groq key | Yes | Same, very fast |
| `ollama` | **Free** | One 2 GB download | **No** | Runs on your own PC, no key, no limits |
| `claude` | Paid | Anthropic key | Yes | Most capable — flip to this any time |
| `free` | **Free** | Nothing | No | Rule-based, always works as a safety net |

Every brain uses the same voice and the same PC controls — only the intelligence
differs. Pick one from the **Brain** dropdown in the Jarvis window and it switches
instantly; your choice is remembered for next time. If a brain is rate-limited or
offline, Jarvis silently drops to the rule-based brain instead of dying.

## Install on ANY computer (5 minutes)

1. **Get the folder onto the PC** — either clone it:
   ```powershell
   git clone <your-repo-url> vondo
   cd vondo
   ```
   or just copy the folder from a USB stick.

2. **Double-click `setup.bat`.** It checks Python, builds a private `.venv`
   inside the folder, installs everything (with a PyAudio fallback for stubborn
   PCs), and opens `.env` for your key. Nothing is installed system-wide.

3. **Paste one free key** into the `.env` file it opens:
   → Gemini: https://aistudio.google.com/app/apikey
   → Groq: https://console.groq.com/keys

   *Don't want a key at all?* Skip this and run **`install_local_llm.bat`**
   instead — see below.

4. **Double-click `start_jarvis.bat`.**

> Requires Python 3.10+ from [python.org](https://python.org/downloads) with
> **"Add Python to PATH"** ticked. That's the only prerequisite.

## Offline AI — no key, no internet, no limits

`install_local_llm.bat` downloads Ollama **and** the model into a `local llm`
folder inside the project (never your C: drive), then wires it up. Afterwards
pick **Ollama** in the Brain dropdown and Jarvis thinks entirely on your own
machine — nothing you say leaves the PC.

Which model to use, on a typical CPU-only PC:

| Model | Size | Feel | Controls your PC? |
|-------|------|------|-------------------|
| **`qwen2.5:3b`** *(default)* | 1.9 GB | Snappy, replies feel instant | ✅ Yes |
| `llama3.2:3b` | 2.0 GB | Similar speed, chattier tone | ✅ Yes |
| `qwen2.5:7b` | 4.7 GB | Noticeably smarter, 3-4s pause | ✅ Yes |
| ~~`phi3:mini`~~ | 2.2 GB | Fast, but **can't call tools** | ❌ No — chat only |

Change it in `.env` (`OLLAMA_MODEL=`) after pulling it with `ollama pull <name>`.
Anything below ~3B params gets unreliable at tool calling, which is what lets
Jarvis actually open apps and set reminders.

## Using it

By default VONDO waits for its **wake word** before acting. Say:

> "**Hey Vondo**, open Chrome"  ·  "**Hey Vondo**, what's the CPU usage?"  ·  "**Hey Vondo**, search for pizza near me"

Say **"goodbye"** to exit. Prefer no wake word? Set `LISTEN_MODE=continuous` in `.env`.

## Switching to the paid Claude brain later

1. Get a key at https://console.anthropic.com
2. In `.env` set:
   ```
   VONDO_BRAIN=claude
   ANTHROPIC_API_KEY=your_anthropic_key
   ```
3. Run again — nothing else changes. (Groq works the same way with `VONDO_BRAIN=groq`.)

## Customising

All in `.env`:

- `ASSISTANT_NAME` / `WAKE_WORD` — rename your assistant
- `USER_TITLE` — how it addresses you (e.g. `sir`, or blank)
- `TTS_VOICE` — pick a Windows voice by name (e.g. `David`), `TTS_RATE` — talking speed
- `LISTEN_MODE` — `wake` or `continuous`

## File map

| File | Purpose |
|------|---------|
| `setup.bat` | **Run this first on a new PC** — builds everything |
| `install_local_llm.bat` | Installs the offline AI brain into `local llm/` |
| `start_jarvis.bat` | Start the window UI · `run.bat` starts the console version |
| `vondo.py` | Main loop — listen → think → act → speak |
| `jarvis_gui.py` | The desktop window, status orb, and Brain dropdown |
| `voice.py` | Microphone (speech-to-text) + speaker (text-to-speech) |
| `actions.py` | The PC controls (open apps, volume, screenshots, power…) |
| `brain_gemini.py` / `brain_groq.py` / `brain_ollama.py` / `brain_claude.py` | The AI brains |
| `brain_free.py` | Offline rule-based brain (no key) |
| `brain_fallback.py` | Catches API failures and drops to the offline brain |
| `llm_tools.py` | Tool definitions shared by the AI brains |
| `config.py` | Reads your `.env` settings |

## Notes

- Speech recognition uses Google's free web API, so it needs an internet
  connection (this is separate from your chosen brain).
- Shutdown/restart are scheduled with a 30-second delay — say **"cancel"** to stop them.
- Everything runs locally on your PC; only your spoken command text goes to the
  chosen brain's API.
