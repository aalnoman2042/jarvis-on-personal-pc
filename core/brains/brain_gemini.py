"""GEMINI brain — natural-language AI via Google Gemini's FREE API tier.

Get a free key at https://aistudio.google.com/app/apikey and put it in .env as
GEMINI_API_KEY. Understands free-form speech, chains PC actions, and answers
questions — all on Google's free tier. Uses the current `google-genai` SDK.
"""
from __future__ import annotations

from google import genai
from google.genai import types

from core import config
from core.tools import llm_tools

# One shared personality for every brain — see config.system_prompt().
SYSTEM_PROMPT = config.system_prompt()


class GeminiBrain:
    name = "gemini"

    def __init__(self) -> None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError(
                "VONDO_BRAIN=gemini but GEMINI_API_KEY is not set in your .env. "
                "Get a free key at https://aistudio.google.com/app/apikey"
            )
        # Keep a reference to the client — if it's garbage-collected its
        # transport closes and later requests fail with "client has been closed".
        self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        # Passing Python callables as tools enables Gemini's automatic function
        # calling — it runs the PC actions itself. The chat keeps history.
        self._chat = self._client.chats.create(
            model=config.GEMINI_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=llm_tools.TOOL_FUNCTIONS,
            ),
        )

    def greeting(self) -> str:
        return config.greeting()

    def handle(self, text: str) -> str:
        if not text.strip():
            return ""
        if any(p in text.lower() for p in ("goodbye", "power down", "go to sleep")):
            return "__EXIT__"
        # Let API errors (rate limits, network) propagate so the fallback
        # wrapper can drop to the offline brain.
        resp = self._chat.send_message(text)
        return (resp.text or "Done.").strip()
