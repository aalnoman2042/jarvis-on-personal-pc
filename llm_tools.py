"""Shared tool definitions for the LLM brains (Gemini + Groq).

- TOOL_FUNCTIONS: plain Python callables for Gemini's automatic function calling.
- OPENAI_TOOLS:   JSON schemas for Groq's OpenAI-style tool calling.
- DISPATCH:       name -> callable, used to execute Groq tool calls.

All of them just forward to actions.py, so PC control is identical across brains.
Wrappers are defined here (not imported from actions) so the type hints are plain
`str` — which Gemini's schema generator introspects reliably.
"""
import actions


def open_app(name: str) -> str:
    """Open a desktop application by name (e.g. 'chrome', 'notepad', 'spotify')."""
    return actions.open_app(name)


def close_app(name: str) -> str:
    """Close a running desktop application by name (e.g. 'chrome', 'notepad')."""
    return actions.close_app(name)


def open_website(target: str) -> str:
    """Open a website. Accepts a shortcut ('youtube'), a domain, or a full URL."""
    return actions.open_website(target)


def web_open_search(query: str) -> str:
    """Open a Google search results page in the browser for the given query."""
    return actions.web_search(query)


def set_reminder(minutes: str, message: str) -> str:
    """Set a spoken reminder. 'minutes' = how many minutes from now (a number),
    'message' = what to remind about. Convert hours to minutes yourself."""
    return actions.set_reminder(minutes, message)


def get_time() -> str:
    """Get the current local time."""
    return actions.get_time()


def get_date() -> str:
    """Get today's date."""
    return actions.get_date()


def system_info() -> str:
    """Get CPU load, memory usage, and battery level of this PC."""
    return actions.system_info()


def control_volume(action: str) -> str:
    """Change system volume. 'action' must be 'up', 'down', or 'mute'."""
    return actions.control_volume(action)


def media_control(action: str) -> str:
    """Control media playback. 'action' = 'play', 'pause', 'next', or 'previous'."""
    return actions.media_control(action)


def take_screenshot() -> str:
    """Capture the screen and save it to the Pictures folder."""
    return actions.take_screenshot()


def lock_screen() -> str:
    """Lock the Windows session."""
    return actions.lock_screen()


def power_control(action: str) -> str:
    """Shut down, restart, or cancel a pending shutdown. Confirm before use.

    'action' = 'shutdown', 'restart', or 'cancel'.
    """
    return actions.power_control(action)


def set_autostart(action: str) -> str:
    """Turn auto-start-on-boot on or off. 'action' = 'enable' or 'disable'.

    When enabled, the assistant launches automatically every time the PC boots.
    """
    return actions.set_autostart(action)


TOOL_FUNCTIONS = [
    open_app, close_app, open_website, web_open_search, set_reminder, get_time,
    get_date, system_info, control_volume, media_control, take_screenshot,
    lock_screen, power_control, set_autostart,
]
DISPATCH = {fn.__name__: fn for fn in TOOL_FUNCTIONS}


def _tool(name: str, desc: str, props: dict | None = None, required: list | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props or {},
                "required": required or [],
            },
        },
    }


_STR = lambda d: {"type": "string", "description": d}  # noqa: E731

# OpenAI-style schemas for Groq (kept in sync with the functions above).
OPENAI_TOOLS = [
    _tool("open_app", "Open a desktop application by name (chrome, notepad, spotify).",
          {"name": _STR("Application name")}, ["name"]),
    _tool("close_app", "Close a running desktop application by name (chrome, notepad).",
          {"name": _STR("Application name")}, ["name"]),
    _tool("open_website", "Open a website: a shortcut like 'youtube', a domain, or a URL.",
          {"target": _STR("Shortcut, domain, or full URL")}, ["target"]),
    _tool("web_open_search", "Open a Google search results page in the browser.",
          {"query": _STR("What to search for")}, ["query"]),
    _tool("set_reminder", "Set a spoken reminder after some minutes from now.",
          {"minutes": _STR("Minutes from now (number)"),
           "message": _STR("What to remind about")}, ["minutes", "message"]),
    _tool("get_time", "Get the current local time."),
    _tool("get_date", "Get today's date."),
    _tool("system_info", "Get CPU, memory, and battery status of this PC."),
    _tool("control_volume", "Change system volume ('up', 'down', or 'mute').",
          {"action": _STR("up, down, or mute")}, ["action"]),
    _tool("media_control", "Control media playback ('play', 'pause', 'next', 'previous').",
          {"action": _STR("play, pause, next, or previous")}, ["action"]),
    _tool("take_screenshot", "Capture the screen to the Pictures folder."),
    _tool("lock_screen", "Lock the Windows session."),
    _tool("power_control", "Shut down, restart, or cancel a shutdown. Confirm first.",
          {"action": _STR("shutdown, restart, or cancel")}, ["action"]),
    _tool("set_autostart", "Turn auto-start-on-boot on or off ('enable' or 'disable').",
          {"action": _STR("enable or disable")}, ["action"]),
]
