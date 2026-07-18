# VONDO — voice assistant for your PC

VONDO listens to your voice, talks back, and controls your Windows PC. It starts
**100% free** and upgrades to the paid Claude brain whenever you want — just one
line in a config file.

## What it can do

- **Open apps & files** — "Hey Vondo, open Chrome", "open Notepad", "open Spotify"
- **Web & search** — "open YouTube", "search for the weather in Dhaka", "open github.com"
- **System control** — "volume up", "mute", "take a screenshot", "how's my PC?", "lock the screen", "shut down"
- **Answer questions** — general knowledge and conversation (with the AI brains)

## The four brains

| `VONDO_BRAIN` | Cost | Needs | Notes |
|---------------|------|-------|-------|
| `gemini` *(default)* | **Free** | Free Google key | Natural language + PC control |
| `groq` | **Free** | Free Groq key | Same, very fast |
| `claude` | Paid | Anthropic key | Most capable — flip to this later |
| `free` | **Free** | Nothing | Rule-based, works fully offline |

Every brain uses the same voice and the same PC controls — only the intelligence differs.

## Setup (5 minutes)

1. **Install Python 3.10+** (you already have 3.13 ✔). Then install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
   > If `pyaudio` fails to install: `pip install pipwin && pipwin install pyaudio`

2. **Get a free API key** for the default Gemini brain:
   → https://aistudio.google.com/app/apikey

3. **Create your config:** copy `.env.example` to `.env` and paste the key:
   ```
   GEMINI_API_KEY=your_key_here
   ```

4. **Run it:**
   ```powershell
   python vondo.py
   ```
   or just double-click **`run.bat`**.

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
| `vondo.py` | Main loop — listen → think → act → speak |
| `voice.py` | Microphone (speech-to-text) + speaker (text-to-speech) |
| `actions.py` | The PC controls (open apps, volume, screenshots, power…) |
| `brain_gemini.py` / `brain_groq.py` / `brain_claude.py` | The AI brains |
| `brain_free.py` | Offline rule-based brain (no key) |
| `llm_tools.py` | Tool definitions shared by the AI brains |
| `config.py` | Reads your `.env` settings |

## Notes

- Speech recognition uses Google's free web API, so it needs an internet
  connection (this is separate from your chosen brain).
- Shutdown/restart are scheduled with a 30-second delay — say **"cancel"** to stop them.
- Everything runs locally on your PC; only your spoken command text goes to the
  chosen brain's API.
