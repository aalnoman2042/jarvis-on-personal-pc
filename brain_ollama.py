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
import urllib.error
import urllib.request

import config
import llm_tools

SYSTEM_PROMPT = (
    f"You are {config.ASSISTANT_NAME}, a witty, efficient voice assistant for the "
    f"user's Windows PC. Replies are spoken aloud, so keep them short, natural, and "
    f"free of markdown, lists, or code. "
    f"You control the PC ONLY through the provided tools. Whenever the user asks for "
    f"the time or date, system/CPU/battery status, to open or close an app, to search "
    f"the web, adjust volume, take a screenshot, lock, or shut down — you MUST call the "
    f"matching tool and then report its result. NEVER say you can't do these things, "
    f"and NEVER reply 'let me check' or 'one moment' without actually calling the tool "
    f"in the same turn. Call the tool immediately, then speak the result. "
    + (f"Address the user as '{config.USER_TITLE}' occasionally. " if config.USER_TITLE else "")
)


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
    MAX_HISTORY = 20

    def __init__(self) -> None:
        if not is_available():
            raise RuntimeError(
                f"VONDO_BRAIN=ollama but no Ollama server at {config.OLLAMA_HOST}. "
                f"Start the Ollama app, then run: ollama pull {config.OLLAMA_MODEL}"
            )
        have = installed_models()
        # Ollama reports "qwen2.5:3b"; accept a bare "qwen2.5" in .env too.
        wanted = config.OLLAMA_MODEL
        if have and not any(m == wanted or m.split(":")[0] == wanted.split(":")[0] for m in have):
            raise RuntimeError(
                f"Ollama is running but the model '{wanted}' isn't downloaded. "
                f"Run: ollama pull {wanted}    (installed: {', '.join(have)})"
            )
        self._messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    def greeting(self) -> str:
        return config.greeting()

    def handle(self, text: str) -> str:
        if not text.strip():
            return ""
        if any(p in text.lower() for p in ("goodbye", "power down", "go to sleep")):
            return "__EXIT__"

        # Snapshot so a bad turn (small models sometimes emit a malformed tool
        # call) can be rolled back and retried without corrupting the history.
        snapshot = list(self._messages)
        last_exc = None
        for attempt in range(2):
            self._messages = list(snapshot)
            self._messages.append({"role": "user", "content": text})
            try:
                reply = self._converse()
                self._trim()
                return reply
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                print(f"[ollama turn failed (attempt {attempt + 1}): {exc}]")
        self._messages = snapshot
        # Raise so the fallback wrapper drops to the offline rule-based brain.
        raise last_exc

    def _converse(self) -> str:
        for _ in range(6):  # tool-call loop, capped
            data = _post(
                f"{config.OLLAMA_HOST}/api/chat",
                {
                    "model": config.OLLAMA_MODEL,
                    "messages": self._messages,
                    "tools": llm_tools.OPENAI_TOOLS,
                    "stream": False,
                    "options": {"temperature": 0.6, "num_predict": 512},
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

    def _trim(self) -> None:
        if len(self._messages) > self.MAX_HISTORY:
            self._messages = self._messages[:1] + self._messages[-(self.MAX_HISTORY - 1):]
