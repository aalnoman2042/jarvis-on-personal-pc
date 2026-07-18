"""GROQ brain — natural-language AI via Groq's FREE API tier (very fast).

Get a free key at https://console.groq.com/keys and put it in .env as
GROQ_API_KEY. Uses OpenAI-style tool calling to control the PC.
"""
from __future__ import annotations

import json

from groq import Groq

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


class GroqBrain:
    name = "groq"
    MAX_HISTORY = 20

    def __init__(self) -> None:
        if not config.GROQ_API_KEY:
            raise RuntimeError(
                "VONDO_BRAIN=groq but GROQ_API_KEY is not set in your .env. "
                "Get a free key at https://console.groq.com/keys"
            )
        self._client = Groq(api_key=config.GROQ_API_KEY)
        self._messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    def greeting(self) -> str:
        return config.greeting()

    def handle(self, text: str) -> str:
        if not text.strip():
            return ""
        if any(p in text.lower() for p in ("goodbye", "power down", "go to sleep")):
            return "__EXIT__"

        # Snapshot so a failed turn (e.g. llama's occasional malformed tool call)
        # can be rolled back and retried without corrupting the conversation.
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
                print(f"[groq turn failed (attempt {attempt + 1}): {exc}]")
        self._messages = snapshot  # keep history intact
        # Raise so the fallback wrapper can drop to the offline brain.
        raise last_exc

    def _converse(self) -> str:
        for _ in range(6):  # tool-call loop, capped
            resp = self._client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=self._messages,
                tools=llm_tools.OPENAI_TOOLS,
                tool_choice="auto",
                max_tokens=1024,
            )
            msg = resp.choices[0].message
            assistant = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                assistant["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]
            self._messages.append(assistant)

            if not msg.tool_calls:
                return (msg.content or "Done.").strip()

            for tc in msg.tool_calls:
                fn = llm_tools.DISPATCH.get(tc.function.name)
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    if not isinstance(args, dict):  # no-arg tools can return 'null'
                        args = {}
                    result = fn(**args) if fn else f"Unknown tool {tc.function.name}."
                except Exception as exc:  # noqa: BLE001
                    result = f"Tool error: {exc}"
                self._messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": str(result)}
                )
        return "Done."

    def _trim(self) -> None:
        # Keep the system prompt + the most recent messages.
        if len(self._messages) > self.MAX_HISTORY:
            self._messages = self._messages[:1] + self._messages[-(self.MAX_HISTORY - 1):]
