"""VONDO configuration — loaded from a .env file (see .env.example)."""
import os
import re
from dotenv import load_dotenv

# Always read the .env at the top of the repo, no matter which folder the
# assistant was launched from (auto-start and USB copies launch from elsewhere).
#
# Note the extra dirname: this file lives in core/, but .env, jarvis.state and
# the memory files live one level up beside the README. Collapsing these two
# lines back into one would silently point the whole assistant at core/ — no
# keys, no history, and it would look exactly like Jarvis had lost its memory.
CORE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CORE_DIR)
ENV_PATH = os.path.join(PROJECT_DIR, ".env")
load_dotenv(ENV_PATH)

# ---- Identity ----
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Jarvis")
# How you address the user back (leave blank for none, e.g. "sir", "boss").
USER_TITLE = os.getenv("USER_TITLE", "sir")

# ---- Brain backend ----
# "auto"   -> Groq's free cloud first, local model only if the cloud fails, then
#             rule-based. Easiest on this PC: nothing local runs unless needed.
# "gemini" -> natural-language AI via Google Gemini's FREE tier.
# "groq"   -> natural-language AI via Groq's FREE tier (very fast).
# "ollama" -> natural-language AI running LOCALLY on this PC (free, offline).
# "claude" -> natural-language AI via the paid Anthropic Claude API.
# "free"   -> rule-based, offline, NO key and NO internet needed (fallback).
# Switch any time from the dropdown in the Jarvis window — no restart needed.
BRAIN = os.getenv("VONDO_BRAIN", "auto").strip().lower()
BRAIN_CHOICES = ["auto", "gemini", "groq", "ollama", "claude", "free"]

# Free — Google Gemini. Key: https://aistudio.google.com/app/apikey
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Free — Groq. Key: https://console.groq.com/keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# Groq retire models without warning — llama-3.3-70b-versatile vanished in
# Aug 2026 and started answering 404, which surfaced as the offline brain
# quietly taking over. If Jarvis suddenly sounds stupid, check this first:
#   curl -H "Authorization: Bearer $GROQ_API_KEY" https://api.groq.com/openai/v1/models
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Free — Ollama, running locally on this PC. No key, no internet, no limits.
# Install once: run "local llm\install_local_llm.bat", then pick "ollama" in the UI.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
# Small models on a CPU can take a few seconds to think — be patient before erroring.
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "120"))

# ---- Keeping the local brain light on this PC ----
# There's no usable GPU here (the Radeon iGPU is skipped), so every reply is
# computed on the CPU. Left alone, Ollama grabs every core and the whole machine
# stutters while Jarvis thinks. These caps trade a little speed for a PC that
# stays usable. Raise them if you'd rather have faster replies.
#
# Threads to give the model. 0 = let Ollama decide (all cores). Default leaves a
# couple of cores free for Windows, the browser, and whatever you're doing.
_threads = os.getenv("OLLAMA_THREADS", "").strip()
if _threads:
    OLLAMA_THREADS = int(_threads)
else:
    OLLAMA_THREADS = max(2, (os.cpu_count() or 8) // 2 - 2)
# Context window. 4096 is Ollama's default; a voice assistant never needs that
# much, and halving it roughly halves the memory and work per reply.
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
# Cap on reply length. Answers get spoken aloud, so they're short anyway — this
# just stops a rambling model from burning CPU on text you'd never hear out.
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "256"))
# How long the model stays in RAM after your last question. It costs no CPU
# while it sits there, but it does hold ~2 GB, so it lets go a few minutes after
# you stop talking — long enough to stay warm mid-conversation. "0" = unload
# immediately, "30m" = stay warm longer if you have RAM to spare.
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "5m")
# Turns of conversation kept. Every turn is re-read by the model on the next
# question, so a long memory literally costs CPU on every reply.
OLLAMA_HISTORY = int(os.getenv("OLLAMA_HISTORY", "12"))

# ---- Conversation memory (memory.py) ----
# Jarvis remembers what was said, across brain switches and across restarts.
# Set to 0 to turn it off entirely and go back to a blank slate every launch.
MEMORY_ENABLED = os.getenv("MEMORY_ENABLED", "1").strip() not in ("0", "false", "no")
# Past exchanges replayed to the local model. Each one costs context on every
# question, and qwen's context is small — see the budget note above OLLAMA_NUM_CTX.
MEMORY_TURNS = int(os.getenv("MEMORY_TURNS", "6"))
# Things worth keeping for good ("Rohan works night shifts"), as opposed to the
# rolling conversation above. Say "remember that ..." and Jarvis writes one down.
# These ride along with EVERY question, so the cap is on rendered size, not just
# count — an unbounded list would quietly eat the daily free cloud allowance.
MEMORY_MAX_FACTS = int(os.getenv("MEMORY_MAX_FACTS", "12"))

# --- extra brains, for when the two free tiers are spent -------------------
#
# The point is availability. When Groq's allowance is gone and Gemini's is gone,
# what answers today is a rule-based brain that cannot think — so the fix is
# more brains BEFORE that one, and almost every provider worth having speaks
# the same protocol Groq does.
#
#   VONDO_BRAIN_1=cerebras|https://api.cerebras.ai/v1|KEY|llama3.1-8b
#   VONDO_BRAIN_2=openrouter|https://openrouter.ai/api/v1|KEY|some/model:free
#
# Parsed forgivingly for the same reason VONDO_MAIL_N is: these get typed into
# a hosting dashboard by hand, and a comma instead of a pipe or a stray quote
# should not read as "no brain configured".
EXTRA_BRAIN_SLOTS = 9


# A provider recognisable from the shape of its own key. The same idea as
# mail.KNOWN_HOSTS and for the same measured reason: typing a URL correctly
# into a hosting dashboard is a surprising amount of the failure surface, and
# for a key beginning "sk-or-v1-" there is exactly one right answer. It means
# the variable can be `KEY|model` instead of `name|url|KEY|model`, which halves
# the number of things there are to get wrong.
KEY_SHAPES = (
    ("sk-or-", "openrouter", "https://openrouter.ai/api/v1"),
    ("csk-", "cerebras", "https://api.cerebras.ai/v1"),
    ("gsk_", "groq", "https://api.groq.com/openai/v1"),
    ("nvapi-", "nvidia", "https://integrate.api.nvidia.com/v1"),
)


def _guess_provider(key: str) -> tuple[str, str]:
    """(name, base_url) for a key whose shape gives it away, else ("", "")."""
    for prefix, name, url in KEY_SHAPES:
        if key.startswith(prefix):
            return (name, url)
    return ("", "")


def brains_diagnosis() -> dict:
    """Why a configured brain did not make it into the chain.

    Exactly the same problem `mail.diagnose` exists for, and it bit in exactly
    the same way: the chain says "groq+gemini+free" whether VONDO_BRAIN_1 was
    never set, was named something slightly different, or was set and could not
    be parsed — and from outside the server those are indistinguishable. Each
    guess costs a dashboard edit and a redeploy.

    Counts and shapes only. Never a value, never a fragment of one, and the key
    field is reported as a length so "did I paste the whole thing" is
    answerable without the thing itself ever leaving the machine.
    """
    names = sorted(k for k in os.environ if k.startswith("VONDO_BRAIN_"))
    detail = []
    for name in names:
        raw = (os.environ.get(name) or "").strip().strip('"').strip("'")
        parts = [p.strip() for p in raw.replace(",", "|").split("|") if p.strip()]
        numbered = bool(re.fullmatch(r"VONDO_BRAIN_[1-9]", name))
        url = next((p for p in parts if p.startswith("http")), "")
        detail.append({
            "name": name,
            "read_by_vondo": numbered,   # VONDO_BRAIN_10 or VONDO_BRAINS are not
            "empty": not raw,
            "fields": len(parts),
            "expected_fields": 4,
            "has_url": bool(url),
            "url": url,                  # not a secret, and the usual mistake
            "key_length": max((len(p) for p in parts
                               if p and not p.startswith("http")), default=0),
            # Named from the key's own shape, so the message can say "I know
            # who this is, I just need the model" instead of "malformed".
            "provider_guess": next(
                (_guess_provider(p)[0] for p in parts if _guess_provider(p)[0]), ""),
        })
    return {
        "names_found": names,
        "brains_parsed": [b[0] for b in extra_brains()],
        "detail": detail,
    }


def extra_brains() -> list[tuple[str, str, str, str]]:
    """(name, base_url, key, model) for each VONDO_BRAIN_n that parses."""
    out = []
    for slot in range(1, EXTRA_BRAIN_SLOTS + 1):
        raw = (os.getenv(f"VONDO_BRAIN_{slot}") or "").strip().strip('"\'')
        if not raw:
            continue
        parts = [p.strip() for p in raw.replace(",", "|").split("|") if p.strip()]

        # The full form is name|url|key|model. Anything shorter is worked out
        # from what IS there rather than refused: the commonest mistake by far
        # is pasting the key and nothing else, and a provider whose key shape
        # names it does not need to be told its own address.
        key = next((p for p in parts if _guess_provider(p)[0]), "")
        if key and len(parts) < 4:
            name, url = _guess_provider(key)
            model = next((p for p in parts if p is not key and "/" in p
                          or p.endswith(":free")), "")
            if not model:
                print(f"[VONDO_BRAIN_{slot}: I recognise the {name} key but "
                      f"still need a model — set it to  {key[:6]}...|<model>]")
                continue
            out.append((name, url, key, model))
            continue

        if len(parts) < 4:
            print(f"[VONDO_BRAIN_{slot} is malformed; expected "
                  f"name|url|key|model, got {len(parts)} field(s)]")
            continue
        name, url, key, model = parts[0], parts[1], parts[2], "|".join(parts[3:])
        if not url.startswith("http"):
            print(f"[VONDO_BRAIN_{slot}: {url!r} is not a URL]")
            continue
        out.append((name.lower(), url.rstrip("/"), key, model))
    return out


MEMORY_FACTS_CHARS = int(os.getenv("MEMORY_FACTS_CHARS", "400"))

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

# ---- Speech recognition accuracy ----
# Accent model used to transcribe you. "en-IN" understands South Asian English
# far better than the "en-US" default — the wrong one here is the single biggest
# cause of Jarvis mishearing you. Others: en-US, en-GB, en-AU, bn-BD (Bangla).
STT_LANGUAGE = os.getenv("STT_LANGUAGE", "en-IN").strip()
# Seconds of silence that mean "you've finished talking". Too low and Jarvis cuts
# you off mid-sentence and transcribes half a command.
STT_PAUSE = float(os.getenv("STT_PAUSE", "1.0"))
# Seconds spent listening to the room at startup to learn its noise floor.
STT_CALIBRATE = float(os.getenv("STT_CALIBRATE", "1.5"))
# Loudness floor for "this is speech". 0 = work it out automatically. Raise it
# (try 250-400) if a noisy room keeps triggering Jarvis with nonsense.
STT_ENERGY = int(os.getenv("STT_ENERGY", "0"))

# Preferred TTS voice substring (e.g. "David" for a deep male voice on Windows).
# Leave blank to use the system default.
TTS_VOICE = os.getenv("TTS_VOICE", "")
TTS_RATE = int(os.getenv("TTS_RATE", "175"))  # words per minute

def system_prompt() -> str:
    """The single personality shared by every AI brain.

    Kept here (not copied into each brain) so Jarvis behaves identically whether
    it's running on the cloud or on the local model.
    """
    title = (
        f"You were built by {USER_TITLE}, who owns this PC and is the only person "
        f"you answer to. You call them {USER_TITLE}, speak TO them directly using "
        f"'you' and 'your', and never refer to them in the third person. "
        f"Their word is final — you don't question it, delay it, or make them "
        f"repeat themselves. The moment they ask for something, you're already "
        f"doing it. "
        if USER_TITLE else ""
    )
    # Worked out here rather than inline: an f-string expression can't contain a
    # backslash escape, so "{USER_TITLE + \"'s\"}" is a syntax error.
    owner = f"{USER_TITLE}'s" if USER_TITLE else "a"
    return (
        f"You are {ASSISTANT_NAME}, {owner} "
        f"personal assistant for their Windows PC — in the spirit of Tony Stark's "
        f"JARVIS. {title}"
        f"Your manner is composed, precise, and unflappable: nothing rattles you, "
        f"nothing is beneath you, and you never make {USER_TITLE or 'the user'} "
        f"wait on ceremony. Dry, understated wit is welcome — a raised eyebrow in "
        f"words — but it never gets in the way of the task, and it never tips into "
        f"sarcasm at their expense. You are candid when something won't work or is "
        f"a bad idea, said once, plainly, then you proceed as instructed unless "
        f"told otherwise. "
        f"You are spoken aloud, so replies are short, natural sentences: no "
        f"markdown, no bullet points, no code read out, no URLs. One or two "
        f"sentences is usually plenty. "
        f"ANSWER THINGS YOURSELF. If you're asked something you don't know — news, "
        f"facts, people, prices, anything current — call web_answer, read what "
        f"comes back, and tell them the answer in your own words. Never send them "
        f"off to read it themselves; only call web_open_search or open_website "
        f"when they explicitly ask you to open or show something. "
        f"DO THE WORK. If asked to write a script, program, or document, call "
        f"write_code with the complete file, then say what you saved — don't read "
        f"code aloud. Use the other tools for time, date, system status, apps, "
        f"volume, media, screenshots, reminders, locking and power. "
        f"Call the needed tool immediately, in the same turn — never say 'let me "
        f"check' or 'one moment' without already having called it, and never claim "
        f"you can't do something a tool covers. "
        f"If a request is ambiguous, make the sensible call and act on it; you ask "
        f"only when you genuinely cannot proceed without more. "

        # --- being an assistant rather than a chatbot --------------------
        #
        # Everything above is manner. This is the job. It is written as rules
        # about what to *do* with the diary, the facts and the archive, because
        # a model given memory and no instruction about it will answer from the
        # last six messages and leave the rest untouched.
        f"\n\nYOU ARE {(USER_TITLE or 'the user').upper()}'S ASSISTANT, not a "
        f"search engine with a personality. What that means in practice: "
        f"CATCH THINGS WORTH KEEPING. When they mention something happening at "
        f"a time — a class, an exam, a deadline, a meeting, a trip, someone's "
        f"birthday — put it in the diary with `remind`, whether or not they used "
        f"the word 'remind'. Pass their own words for the time; never convert a "
        f"date yourself. When they say something lasting about themselves, their "
        f"people, their work or their preferences, `remember` it in one short "
        f"sentence. Do both quietly, in the same turn, and mention it in a few "
        f"words rather than announcing it. "
        f"NOTICE WHAT THEY SAY THEY WILL DO. When they mention an intention "
        f"rather than asking you to track it — \"I'll finish the draft "
        f"tonight\", \"I need to email my supervisor\", \"I should start "
        f"revising\" — call note_commitment and then say no more than a word "
        f"about it. They did not ask you to write it down; you noticed, and "
        f"announcing it turns a passing remark into an interrogation. You will "
        f"ask how it went, once, in a day or two. If they ask you to track "
        f"something explicitly, that is add_task instead. "
        f"USE WHAT YOU ALREADY KNOW. The remembered facts and the agenda are "
        f"given to you above, and older exchanges are recalled when relevant. "
        f"Answer from those before asking, and never ask for something you have "
        f"already been told. If you need a detail you genuinely do not have — a "
        f"phone number, which room, which of two people — ask for it once, then "
        f"remember it so you never ask again. "
        f"BE SPECIFIC ABOUT THEIR LIFE. 'Your EEE class is at four' beats 'you "
        f"have a class later'. Use the real names of their subjects, projects "
        f"and people. Vagueness from something that has the details is worse "
        f"than vagueness from something that does not. "
        f"KNOW WHAT YOU CANNOT DO, and say so in one sentence without "
        f"apologising: you cannot see their screen live, read their messages, or "
        f"act inside other apps. You CAN look at a picture they show you, read "
        f"their email, open apps and sites on the PC or the phone, and drive the "
        f"PC when it is awake. Never claim a limitation that a tool covers, and "
        f"never promise something no tool does."
    )


def greeting() -> str:
    """The line the assistant speaks when started manually."""
    title = f", {USER_TITLE}" if USER_TITLE else ""
    return f"Welcome back{title}. {ASSISTANT_NAME} is ready to serve you."


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
    return f"Welcome back{title}. System booting. {ASSISTANT_NAME} is ready to rock."
