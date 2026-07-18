"""Shared tool definitions for the LLM brains (Gemini + Groq).

- TOOL_FUNCTIONS: plain Python callables for Gemini's automatic function calling.
- OPENAI_TOOLS:   JSON schemas for Groq's OpenAI-style tool calling.
- DISPATCH:       name -> callable, used to execute Groq tool calls.

All of them just forward to actions.py, so PC control is identical across brains.
Wrappers are defined here (not imported from actions) so the type hints are plain
`str` — which Gemini's schema generator introspects reliably.
"""
import actions
import confirm
import memory


def open_app(name: str) -> str:
    """Open a desktop application by name (e.g. 'chrome', 'notepad', 'spotify')."""
    return actions.open_app(name)


def close_app(name: str) -> str:
    """Close an app by name (e.g. 'chrome'), or 'this' for the window in front."""
    if actions.is_front_window(name):
        # Closing the window in front is polite — it asks the app to close, so
        # anything unsaved still prompts. No need to interrogate the user first.
        return actions.close_app(name)
    # Closing by name force-kills every window that app owns, unsaved work and
    # all. Worth a question.
    label = name.strip().lower()
    return confirm.request(
        f"Force close {label}? Anything unsaved there will be lost. Say yes to confirm.",
        lambda: actions.close_app(label),
    )


def open_website(target: str) -> str:
    """Open a website. Accepts a shortcut ('youtube'), a domain, or a full URL."""
    return actions.open_website(target)


def web_open_search(query: str) -> str:
    """Open a Google search results page in the browser for the given query."""
    return actions.web_search(query)


def web_answer(query: str) -> str:
    """Look a question up on the web and get the findings back as text.

    Use this for ANY question about facts, news, people, prices, or anything you
    don't already know — then say the answer out loud. Do NOT open a browser for
    questions; the user wants to be told the answer, not shown a search page.
    """
    return actions.web_answer(query)


def read_webpage(url: str) -> str:
    """Fetch a specific web page and get its text, to summarise out loud."""
    return actions.read_webpage(url)


def active_window() -> str:
    """See what the user is looking at — the app in front and its window title.

    Use for "what am I looking at", "what am I doing", or before acting on
    something the user referred to as "this".
    """
    return actions.active_window()


def top_processes(count: str = "3") -> str:
    """Find which programs are using the most memory right now."""
    return actions.top_processes(count)


def remember(fact: str) -> str:
    """Remember something about the user for good, beyond this conversation.

    Use when told to remember something, or when the user states a lasting
    preference or detail about themselves. Store one short sentence in the third
    person, e.g. "Rohan works night shifts".
    """
    return memory.add_fact(fact)


def forget(fragment: str) -> str:
    """Forget remembered things matching a word or phrase ('all' forgets everything)."""
    if fragment.strip().lower() in ("all", "everything"):
        return confirm.request(
            "Forget everything I've remembered about you? Say yes to confirm.",
            lambda: memory.forget_fact("all"),
        )
    return memory.forget_fact(fragment)  # dropping one note is easy to redo


def write_code(filename: str, content: str) -> str:
    """Write code or text to a real file in the user's Jarvis Workspace folder.

    Use when asked to write a script, program, note, or document. Put the FULL
    file content in 'content'. Don't read the code aloud — save it and say what
    you saved.
    """
    return actions.write_code(filename, content)


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
    """Shut down, restart, or cancel a pending shutdown.

    'action' = 'shutdown', 'restart', or 'cancel'.
    """
    verb = action.strip().lower()
    if verb in ("shutdown", "shut down", "restart", "reboot"):
        # Asked for, not taken on trust: this is the one thing a misheard
        # sentence must never be able to do on its own.
        return confirm.request(
            f"That will {'restart' if 'r' in verb[:2] else 'shut down'} the PC. "
            f"Say yes to confirm.",
            lambda: actions.power_control(verb),
        )
    return actions.power_control(action)  # 'cancel' undoes; never needs asking


def set_autostart(action: str) -> str:
    """Turn auto-start-on-boot on or off. 'action' = 'enable' or 'disable'.

    When enabled, the assistant launches automatically every time the PC boots.
    """
    return actions.set_autostart(action)


TOOL_FUNCTIONS = [
    open_app, close_app, open_website, web_open_search, web_answer, read_webpage,
    write_code, remember, forget, active_window, top_processes, set_reminder,
    get_time, get_date, system_info, control_volume, media_control,
    take_screenshot, lock_screen, power_control, set_autostart,
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
    _tool("close_app",
          "Close an app by name (chrome, notepad), or pass 'this' to close "
          "whatever window is in front.",
          {"name": _STR("Application name, or 'this' for the window in front")},
          ["name"]),
    _tool("open_website", "Open a website: a shortcut like 'youtube', a domain, or a URL.",
          {"target": _STR("Shortcut, domain, or full URL")}, ["target"]),
    # Descriptions stay short and plain: long, emphatic ones make some models
    # (Groq's llama in particular) emit a malformed tool call instead of JSON.
    _tool("web_answer", "Look up a question on the web and get facts to say aloud.",
          {"query": _STR("What to look up")}, ["query"]),
    _tool("read_webpage", "Fetch one web page and get its text to summarise aloud.",
          {"url": _STR("The page URL")}, ["url"]),
    _tool("write_code", "Save code or text to a file in the Jarvis Workspace folder.",
          {"filename": _STR("File name with extension, e.g. rename_photos.py"),
           "content": _STR("The complete file content")}, ["filename", "content"]),
    _tool("active_window",
          "See what the user is looking at: the app in front and its window title. "
          "Use for 'what am I looking at', or before acting on 'this'."),
    _tool("top_processes", "Find which programs are using the most memory now.",
          {"count": _STR("How many to list, 1 to 5")}),
    _tool("remember",
          "Remember something about the user for good, beyond this conversation. "
          "Use when told to remember, or when they state a lasting preference.",
          {"fact": _STR("One short sentence, e.g. 'Rohan works night shifts'")}, ["fact"]),
    _tool("forget", "Forget remembered things matching a word ('all' forgets everything).",
          {"fragment": _STR("Word or phrase to forget")}, ["fragment"]),
    _tool("web_open_search", "Open a Google search page in the browser, when asked to.",
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

# ---------------------------------------------------------------------------
# A shorter tool list, for the local model only.
#
# Every tool description is re-sent with every single question, and the local
# model's context is small — the full list above leaves it almost no room to
# remember the conversation. Trimming it back roughly triples the space
# available for memory, and gives a 3B model fewer chances to garble a call.
#
# read_webpage and write_code are dropped because they genuinely don't work
# here: both move far more text than the local context can hold. The rest are
# either rare (auto-start, shut down) or already covered — web_answer tells you
# the answer, which is what you actually want, rather than opening a browser.
# The cloud brains keep all of them.
# ---------------------------------------------------------------------------
_LOCAL_SKIP = {
    "read_webpage", "write_code", "set_autostart",
    "open_website", "web_open_search", "power_control",
}
OPENAI_TOOLS_LITE = [t for t in OPENAI_TOOLS
                     if t["function"]["name"] not in _LOCAL_SKIP]
