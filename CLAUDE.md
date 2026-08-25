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
