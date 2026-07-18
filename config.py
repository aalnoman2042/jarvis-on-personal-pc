"""VONDO configuration — loaded from a .env file (see .env.example)."""
import os
from dotenv import load_dotenv

# Always read the .env sitting next to this file, no matter which folder the
# assistant was launched from (auto-start and USB copies launch from elsewhere).
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(PROJECT_DIR, ".env")
load_dotenv(ENV_PATH)

# ---- Identity ----
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Jarvis")
# How you address the user back (leave blank for none, e.g. "sir", "boss").
USER_TITLE = os.getenv("USER_TITLE", "sir")

# ---- Brain backend ----
# "gemini" -> natural-language AI via Google Gemini's FREE tier (default).
# "groq"   -> natural-language AI via Groq's FREE tier (very fast).
# "ollama" -> natural-language AI running LOCALLY on this PC (free, offline).
# "claude" -> natural-language AI via the paid Anthropic Claude API.
# "free"   -> rule-based, offline, NO key and NO internet needed (fallback).
# Switch any time from the dropdown in the Jarvis window — no restart needed.
BRAIN = os.getenv("VONDO_BRAIN", "gemini").strip().lower()
BRAIN_CHOICES = ["gemini", "groq", "ollama", "claude", "free"]

# Free — Google Gemini. Key: https://aistudio.google.com/app/apikey
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Free — Groq. Key: https://console.groq.com/keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Free — Ollama, running locally on this PC. No key, no internet, no limits.
# Install once: run "local llm\install_local_llm.bat", then pick "ollama" in the UI.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
# Small models on a CPU can take a few seconds to think — be patient before erroring.
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "120"))

# Paid — Anthropic Claude. Key: https://console.anthropic.com
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")

# ---- Voice / listening ----
# "wake"       -> only acts after hearing the wake word (say "Vondo, open chrome").
# "continuous" -> acts on every phrase it hears (no wake word needed).
LISTEN_MODE = os.getenv("LISTEN_MODE", "wake").strip().lower()
WAKE_WORD = os.getenv("WAKE_WORD", "jarvis").strip().lower()

# Microphone device index (run `python list_mics.py` to see them).
# Leave blank to use the Windows default input device.
_mic = os.getenv("MIC_INDEX", "").strip()
MIC_INDEX = int(_mic) if _mic else None

# Preferred TTS voice substring (e.g. "David" for a deep male voice on Windows).
# Leave blank to use the system default.
TTS_VOICE = os.getenv("TTS_VOICE", "")
TTS_RATE = int(os.getenv("TTS_RATE", "175"))  # words per minute


def greeting() -> str:
    """The line the assistant speaks when started manually."""
    title = f", {USER_TITLE}" if USER_TITLE else ""
    return f"Welcome back{title}. {ASSISTANT_NAME} online and ready."


def set_brain(name: str) -> None:
    """Switch the active brain and remember it in .env for next time.

    Called by the dropdown in the Jarvis window, so the choice survives restarts.
    """
    global BRAIN
    name = name.strip().lower()
    if name not in BRAIN_CHOICES:
        raise ValueError(f"Unknown brain '{name}'. Choose one of: {', '.join(BRAIN_CHOICES)}")
    BRAIN = name
    _write_env("VONDO_BRAIN", name)


def _write_env(key: str, value: str) -> None:
    """Set key=value in .env, replacing the existing line if there is one."""
    try:
        with open(ENV_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    try:
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as exc:
        print(f"[couldn't save {key} to .env: {exc}]")


def boot_greeting() -> str:
    """The line the assistant speaks when launched automatically at PC boot."""
    title = f", {USER_TITLE}" if USER_TITLE else ""
    return f"Welcome back{title}. System booting. {ASSISTANT_NAME} is online and ready."
