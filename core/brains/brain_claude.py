"""CLAUDE brain — natural-language AI via the Anthropic Claude API (paid).

Enable later by setting VONDO_BRAIN=claude and ANTHROPIC_API_KEY in your .env.
It understands free-form speech, chains PC actions, answers questions, and can
search the web for current information. The PC actions are the same ones the
free brain uses (from actions.py), exposed to Claude as tools.
"""
from __future__ import annotations

import anthropic
from anthropic import beta_tool

from core.lazy import actions
from core import config


# ---- PC-control actions exposed to Claude as tools ----------------------------
# The docstrings ARE the tool descriptions Claude reads, so keep them clear.

@beta_tool
def open_app(name: str) -> str:
    """Open a desktop application by name, e.g. 'chrome', 'notepad', 'spotify'."""
    return actions.open_app(name)


@beta_tool
def close_app(name: str) -> str:
    """Close a running desktop application by name, e.g. 'chrome', 'notepad'."""
    return actions.close_app(name)


@beta_tool
def open_website(target: str) -> str:
    """Open a website. Accepts a shortcut like 'youtube', a domain, or a full URL."""
    return actions.open_website(target)


@beta_tool
def web_open_search(query: str) -> str:
    """Open a Google search results page in the browser for the given query.

    Use this only when the user wants the browser opened. To ANSWER a question
    yourself, use the built-in web_search tool or your own knowledge instead.
    """
    return actions.web_search(query)


@beta_tool
def set_reminder(minutes: str, message: str) -> str:
    """Set a spoken reminder. minutes = how many minutes from now; message = what
    to remind about. Convert hours to minutes yourself."""
    return actions.set_reminder(minutes, message)


@beta_tool
def get_time() -> str:
    """Get the current local time."""
    return actions.get_time()


@beta_tool
def get_date() -> str:
    """Get today's date."""
    return actions.get_date()


@beta_tool
def system_info() -> str:
    """Get CPU load, memory usage, and battery level of this PC."""
    return actions.system_info()


@beta_tool
def control_volume(action: str) -> str:
    """Change system volume. action must be 'up', 'down', or 'mute'."""
    return actions.control_volume(action)


@beta_tool
def media_control(action: str) -> str:
    """Control media playback. action = 'play', 'pause', 'next', or 'previous'."""
    return actions.media_control(action)


@beta_tool
def take_screenshot() -> str:
    """Capture the screen and save it to the Pictures folder."""
    return actions.take_screenshot()


@beta_tool
def lock_screen() -> str:
    """Lock the Windows session."""
    return actions.lock_screen()


@beta_tool
def power_control(action: str) -> str:
    """Shut down, restart, or cancel a pending shutdown of this PC.

    action = 'shutdown', 'restart', or 'cancel'. ALWAYS confirm with the user
    before shutting down or restarting.
    """
    return actions.power_control(action)


@beta_tool
def set_autostart(action: str) -> str:
    """Turn auto-start-on-boot on or off. action = 'enable' or 'disable'."""
    return actions.set_autostart(action)


CLIENT_TOOLS = [
    open_app, close_app, open_website, web_open_search, set_reminder, get_time,
    get_date, system_info, control_volume, media_control, take_screenshot,
    lock_screen, power_control, set_autostart,
]
# Anthropic-hosted web search so VONDO can answer questions about current events.
SERVER_TOOLS = [{"type": "web_search_20260209", "name": "web_search"}]

# One shared personality for every brain — see config.system_prompt().
SYSTEM_PROMPT = config.system_prompt()


class ClaudeBrain:
    name = "claude"
    MAX_HISTORY = 20  # keep the last N messages so context stays lean

    def __init__(self) -> None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "VONDO_BRAIN=claude but ANTHROPIC_API_KEY is not set in your .env"
            )
        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self._messages: list[dict] = []

    def greeting(self) -> str:
        return config.greeting()

    def handle(self, text: str) -> str:
        if not text.strip():
            return ""
        if any(p in text.lower() for p in ("goodbye", "power down", "go to sleep")):
            return "__EXIT__"

        self._messages.append({"role": "user", "content": text})

        # Run the tool-use loop, restarting on pause_turn (long web searches).
        last = None
        for _ in range(6):  # cap restarts
            runner = self._client.beta.messages.tool_runner(
                model=config.CLAUDE_MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=CLIENT_TOOLS + SERVER_TOOLS,
                output_config={"effort": "low"},  # snappy replies for voice
                messages=self._messages,
            )
            last = None
            for message in runner:
                last = message
                self._messages.append({"role": "assistant", "content": message.content})
                tool_response = runner.generate_tool_call_response()
                if tool_response is not None:
                    self._messages.append(tool_response)
            if last is None or last.stop_reason != "pause_turn":
                break

        self._messages = self._messages[-self.MAX_HISTORY:]  # trim history

        if last is None:
            return "Sorry, I didn't catch that."
        spoken = " ".join(
            b.text for b in last.content if getattr(b, "type", "") == "text"
        ).strip()
        return spoken or "Done."
