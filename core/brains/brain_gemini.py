"""GEMINI brain — natural-language AI via Google Gemini's FREE API tier.

Get a free key at https://aistudio.google.com/app/apikey and put it in .env as
GEMINI_API_KEY. Understands free-form speech, chains PC actions, and answers
questions — all on Google's free tier. Uses the current `google-genai` SDK.
"""
from __future__ import annotations

from google import genai
from google.genai import types

from core import config
from core import memory
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

        # The remembered facts, the diary, today's date and anything the index
        # recalls all live in memory.system_prompt() — and none of it was
        # reaching here. `system_instruction` is fixed when the chat is created,
        # from config.system_prompt(), which is the persona WITHOUT any of that.
        # So Gemini knew Jarvis's manner and nothing whatever about Rohan, and
        # since Gemini is what answers when Groq's free tier runs out, running
        # out looked exactly like Jarvis forgetting everything.
        #
        # Prepended to the message instead, because the SDK will not let the
        # system instruction be changed on a live chat and rebuilding the chat
        # every turn would throw away Gemini's own history with it.
        prompt = memory.system_prompt(text)
        message = f"{prompt}\n\n---\nThey now say: {text}" if prompt else text

        # Let API errors (rate limits, network) propagate so the fallback
        # wrapper can drop to the offline brain.
        resp = self._chat.send_message(message)
        return (resp.text or "Done.").strip()
