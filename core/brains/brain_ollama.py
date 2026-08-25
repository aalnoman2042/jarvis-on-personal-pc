"""OLLAMA brain — natural-language AI running LOCALLY on your own PC.

No API key, no internet, no rate limits, nothing leaves your machine. Needs the
Ollama app running (it starts itself) and a model pulled once, e.g.:

    ollama pull qwen2.5:3b

Set VONDO_BRAIN=ollama in .env, or just pick "ollama" in the Jarvis window.

Uses Ollama's OpenAI-compatible tool calling, so PC control works exactly like
the Groq brain. Talks over plain HTTP so it needs no extra Python package.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request

from core import config
from core.tools import llm_tools
from core import memory

# One shared personality for every brain — see config.system_prompt().
SYSTEM_PROMPT = config.system_prompt()


def _post(url: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def is_available() -> bool:
    """True if the Ollama server is running and reachable."""
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_HOST}/api/tags", timeout=2):
            return True
    except Exception:  # noqa: BLE001
        return False


def _history_budget(prompt: str) -> int:
    """Characters of past conversation that will actually fit this turn.

    The model's context has to hold the persona, every tool description, the
    conversation and the reply. Whatever is left after the first three is all
    the memory there is room for — and if we overrun it, llama.cpp drops the
    oldest tokens, which is exactly where the persona sits.
    """
    reserved = len(prompt) + len(json.dumps(llm_tools.OPENAI_TOOLS_LITE))
    # Roughly four characters per token, less a margin for the chat formatting
    # the server adds around every message.
    spare = (config.OLLAMA_NUM_CTX - config.OLLAMA_NUM_PREDICT) * 4 - reserved - 600
    return max(0, spare)


def _server_exe() -> str:
    """Path to ollama.exe — the copy in "local llm", else one on PATH."""
    local = os.path.join(config.PROJECT_DIR, "local llm", "ollama", "ollama.exe")
    if os.path.exists(local):
        return local
    from shutil import which
    return which("ollama") or ""


def ensure_server(timeout: float = 25.0) -> bool:
    """Start the Ollama server if it isn't already up, and wait for it.

    Called only when the local brain is actually about to answer something, so
    nothing runs in the background while Jarvis is idle or while the cloud brain
    is handling everything. Launched at low priority so a reply never makes the
    rest of the PC stutter.
    """
    if is_available():
        return True
    exe = _server_exe()
    if not exe:
        return False
    env = dict(os.environ)
    # Keep models in the project folder and one model in RAM at a time.
    env.setdefault("OLLAMA_MODELS", os.path.join(config.PROJECT_DIR, "local llm", "models"))
    env["OLLAMA_MAX_LOADED_MODELS"] = "1"
    env["OLLAMA_KEEP_ALIVE"] = config.OLLAMA_KEEP_ALIVE
    creation = 0
    if os.name == "nt":
        # No console window, and below-normal priority so Windows keeps the
        # foreground app smooth while the model thinks.
        creation = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
    try:
        subprocess.Popen(
            [exe, "serve"], env=env, creationflags=creation,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[couldn't start the local AI server: {exc}]")
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_available():
            return True
        time.sleep(0.4)
    return False


def stop_server() -> None:
    """Shut the local model down and free its RAM (used when Jarvis exits)."""
    if os.name != "nt":
        return
    subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"],
                   capture_output=True, check=False)
    subprocess.run(["taskkill", "/F", "/IM", "ollama app.exe"],
                   capture_output=True, check=False)


def installed_models() -> list[str]:
    """Names of the models pulled on this PC (empty if Ollama isn't running)."""
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_HOST}/api/tags", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", [])]
    except Exception:  # noqa: BLE001
        return []


class OllamaBrain:
    name = "ollama"
    # How much conversation to remember lives in memory.py / MEMORY_TURNS now.

    def __init__(self) -> None:
        # Boots the server on demand — it isn't running until this moment.
        if not ensure_server():
            raise RuntimeError(
                f"Couldn't reach or start an Ollama server at {config.OLLAMA_HOST}. "
                f"Run install_local_llm.bat once, then: ollama pull {config.OLLAMA_MODEL}"
            )
        have = installed_models()
        # Ollama reports "qwen2.5:3b"; accept a bare "qwen2.5" in .env too.
        wanted = config.OLLAMA_MODEL
        if have and not any(m == wanted or m.split(":")[0] == wanted.split(":")[0] for m in have):
            raise RuntimeError(
                f"Ollama is running but the model '{wanted}' isn't downloaded. "
                f"Run: ollama pull {wanted}    (installed: {', '.join(have)})"
            )
        self._messages: list[dict] = []

    def greeting(self) -> str:
        return config.greeting()

    def handle(self, text: str) -> str:
        if not text.strip():
            return ""
        if any(p in text.lower() for p in ("goodbye", "power down", "go to sleep")):
            return "__EXIT__"

        last_exc = None
        for attempt in range(2):
            # Rebuilt from shared memory every turn, so this brain can pick up a
            # conversation another brain was handling. Nothing carries over
            # between turns here, so a garbled reply (which small models do emit)
            # can't corrupt anything — retrying just rebuilds a clean list.
            # Built fresh each turn, so something you asked it to remember a
            # moment ago is already in play — no restart needed. History is
            # sized to whatever context is actually left after the persona and
            # the tool list, so it can never push the persona out.
            prompt = memory.system_prompt()
            self._messages = memory.as_openai(
                prompt, text, max_chars=_history_budget(prompt)
            )
            try:
                return self._converse()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                print(f"[ollama turn failed (attempt {attempt + 1}): {exc}]")
        # Raise so the fallback wrapper drops to the offline rule-based brain.
        raise last_exc

    def _converse(self) -> str:
        for _ in range(6):  # tool-call loop, capped
            data = _post(
                f"{config.OLLAMA_HOST}/api/chat",
                {
                    "model": config.OLLAMA_MODEL,
                    "messages": self._messages,
                    # The shorter list — the full one leaves this model almost no
                    # context left to remember the conversation with.
                    "tools": llm_tools.OPENAI_TOOLS_LITE,
                    "stream": False,
                    # Deliberately modest — see the tuning notes in config.py.
                    # Replies are spoken, so a smaller context and shorter answer
                    # cost nothing you'd notice but keep the PC responsive.
                    "keep_alive": config.OLLAMA_KEEP_ALIVE,
                    "options": {
                        "temperature": 0.6,
                        "num_predict": config.OLLAMA_NUM_PREDICT,
                        "num_ctx": config.OLLAMA_NUM_CTX,
                        "num_thread": config.OLLAMA_THREADS,
                    },
                },
                timeout=config.OLLAMA_TIMEOUT,
            )
            msg = data.get("message", {}) or {}
            calls = msg.get("tool_calls") or []
            assistant = {"role": "assistant", "content": msg.get("content", "") or ""}
            if calls:
                assistant["tool_calls"] = calls
            self._messages.append(assistant)

            if not calls:
                return (msg.get("content") or "Done.").strip()

            for call in calls:
                fn_spec = call.get("function", {}) or {}
                fn = llm_tools.DISPATCH.get(fn_spec.get("name", ""))
                try:
                    # Ollama returns arguments already decoded as an object.
                    args = fn_spec.get("arguments") or {}
                    if isinstance(args, str):
                        args = json.loads(args or "{}")
                    if not isinstance(args, dict):
                        args = {}
                    # Small models sometimes pass numbers where we expect strings.
                    args = {k: (v if isinstance(v, str) else str(v)) for k, v in args.items()}
                    result = fn(**args) if fn else f"Unknown tool {fn_spec.get('name')}."
                except Exception as exc:  # noqa: BLE001
                    result = f"Tool error: {exc}"
                self._messages.append(
                    {"role": "tool", "content": str(result),
                     "tool_name": fn_spec.get("name", "")}
                )
        return "Done."
