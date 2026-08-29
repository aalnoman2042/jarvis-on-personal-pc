"""Any OpenAI-compatible provider, as a brain in the chain.

Rohan's reason for this is availability, not variety: when Groq's free tier is
spent and Gemini's is spent, what answers is a rule-based brain that cannot
think. The fix is not a better last resort — it is more brains before it, and
almost every provider worth having speaks the same protocol Groq does.

So this is `GroqBrain`'s shape with the endpoint moved into configuration. Add
`VONDO_BRAIN_1=cerebras|https://api.cerebras.ai/v1|<key>|llama3.1-8b` and there
is a third brain; add another line and there is a fourth. No code, no new file,
no schema to write — `llm_tools.OPENAI_TOOLS` already describes every tool in
the format all of these expect.

**GroqBrain is deliberately left alone.** It carries a rollback-and-retry for
the malformed no-arg tool calls llama-3.3 emits, learned the hard way and
covered by tests. Generalising it would have put a working, exercised brain at
risk to save a file. This is the new thing; that is the proven one.

Same contract as every other brain: `handle(text) -> str`, and construction
FAILS if the provider is not actually usable, because `factory` decides
availability by trying rather than by asking.
"""
from __future__ import annotations

import json

from core import config
from core import memory
from core.tools import llm_tools

# The provider gets this many rounds of "call a tool, look at the result" before
# the turn is cut short. Same cap and same reason as brain_groq: a model that
# has not finished in six is looping, and a loop on somebody else's free tier
# is the most expensive way to fail.
MAX_TOOL_ROUNDS = 6


class OpenAIBrain:
    """One OpenAI-compatible endpoint, wearing the brain interface."""

    def __init__(self, name: str, base_url: str, api_key: str, model: str) -> None:
        if not (base_url and api_key and model):
            raise RuntimeError(f"{name}: needs a URL, a key and a model")
        try:
            from openai import OpenAI
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("the openai package is not installed") from exc
        self.name = name
        self._model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=30.0)

    def greeting(self) -> str:
        return config.greeting()

    def handle(self, text: str) -> str:
        if not text.strip():
            return ""
        if any(p in text.lower() for p in ("goodbye", "power down", "go to sleep")):
            return "__EXIT__"

        # Rebuilt every turn, like Groq's. The recall block is built from what
        # was just said, and a fact remembered a moment ago has to be in play
        # without a restart.
        prompt = memory.system_prompt(text)
        messages = memory.as_openai(prompt, text)

        for _ in range(MAX_TOOL_ROUNDS):
            reply = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=llm_tools.OPENAI_TOOLS,
                tool_choice="auto",
                max_tokens=800,
            )
            choice = reply.choices[0].message
            calls = getattr(choice, "tool_calls", None)
            if not calls:
                said = (choice.content or "").strip()
                if said:
                    return said
                # Nothing at all, and nothing raised. Measured against a real
                # free model: it accepted the request, returned 200, and sent
                # back an empty message — which is the worst possible shape,
                # because FallbackBrain only moves on when something RAISES, so
                # an empty string travels all the way to the screen as silence.
                #
                # The usual cause is that the model does not do tool calling
                # and has no idea what to make of forty tool schemas. A brain
                # that can talk but not act is still far better than the
                # rule-based one, so it is asked again with the tools removed
                # rather than written off.
                return self._without_tools(prompt, text)

            messages.append({
                "role": "assistant",
                "content": choice.content or "",
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name,
                                  "arguments": c.function.arguments or "{}"}}
                    for c in calls],
            })
            for call in calls:
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": self._run(call),
                })

        # Hitting the cap is not success and must not be reported as such. Groq
        # returned a bare "Done." here for a long time, which reads as a
        # finished job and is how a truncated sequence goes unnoticed.
        return ("I got part-way through that and ran out of steps — ask me "
                "again and I'll pick up where the useful part was.")

    def _without_tools(self, prompt: str, text: str) -> str:
        """Ask again with no tools at all, for a model that cannot use them.

        Raises if this is empty too. Raising matters: it is the only thing that
        makes the fallback chain move on, and a brain that returns silence
        without complaining is worse than one that is plainly broken.
        """
        reply = self._client.chat.completions.create(
            model=self._model,
            messages=memory.as_openai(prompt, text),
            max_tokens=800,
        )
        said = (reply.choices[0].message.content or "").strip()
        if not said:
            raise RuntimeError(
                f"{self.name} returned an empty answer, with and without tools")
        return said


    def _run(self, call) -> str:
        """One tool call. Never raises: a broken tool must not end the turn."""
        name = getattr(call.function, "name", "")
        try:
            args = json.loads(call.function.arguments or "{}")
        except ValueError:
            # Some providers emit arguments that are not quite JSON. A
            # no-argument tool is the common case and is worth rescuing rather
            # than failing the whole turn over.
            args = {}
        function = llm_tools.DISPATCH.get(name)
        if function is None:
            return f"There is no tool called {name}."
        try:
            return str(function(**args))
        except TypeError:
            try:
                return str(function())
            except Exception as exc:  # noqa: BLE001
                return f"That didn't work: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"That didn't work: {exc}"
