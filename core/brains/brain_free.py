"""FREE brain — a rule-based command engine. No API key, no cost, works offline.

It matches keywords in what you say to the actions in actions.py. For anything
it doesn't recognise as a command, it falls back to a web search so you still
get an answer. Upgrade to the Claude brain later for true natural language.
"""
from __future__ import annotations

import re

from core.lazy import actions
from core import config
from core.tools import llm_tools

# Things you can "turn off" that are emphatically not the computer. Without
# this, "turn off the music" matched the shutdown rule and powered the PC down
# mid-sentence — the volume and media rules below never got a look in.
_NOT_THE_PC = (
    "music", "song", "playback", "track", "audio", "sound", "volume", "media",
    "light", "lamp", "tv", "screen", "display", "monitor", "alarm", "timer",
    "reminder", "fan", "wifi", "bluetooth", "notification",
)


def _means_the_pc(text: str) -> bool:
    """True if "shut down" / "turn off" was aimed at the PC and nothing else."""
    return not any(word in text for word in _NOT_THE_PC)


class FreeBrain:
    name = "free"

    def greeting(self) -> str:
        return config.greeting()

    def handle(self, text: str) -> str:
        """Turn a spoken phrase into an action and return what to say back."""
        t = text.lower().strip()
        if not t:
            return ""

        # --- Small talk / control ---
        if any(w in t for w in ("hello", "hi ", "hey", "are you there")):
            return "Yes, I'm here."
        if any(w in t for w in ("thank you", "thanks")):
            return "You're welcome."
        if any(p in t for p in ("goodbye", "exit", "quit", "shut down vondo",
                                 "go to sleep", "stop listening")):
            return "__EXIT__"

        # --- Reminders / timers ---
        m = re.search(
            r"(?:remind me|set (?:a )?(?:reminder|timer)|remind)\D*?(\d+)\s*"
            r"(second|sec|minute|min|hour|hr)s?(?:\s+(?:to|about|that|for)\s+(.+))?",
            t,
        )
        if m:
            n = float(m.group(1))
            unit = m.group(2)
            msg = (m.group(3) or "your reminder").strip()
            if unit.startswith("sec"):
                mins = n / 60
            elif unit.startswith(("hour", "hr")):
                mins = n * 60
            else:
                mins = n
            return actions.set_reminder(mins, msg)

        # --- Time / date ---
        if "time" in t:
            return actions.get_time()
        if "date" in t or "what day" in t or "today" in t:
            return actions.get_date()

        # --- System info ---
        if any(w in t for w in ("system", "cpu", "memory", "ram", "battery",
                                "how's my pc", "hows my pc", "how is my pc",
                                "my pc doing", "status")):
            return actions.system_info()

        # --- Auto-start toggle ---
        if "auto start" in t or "autostart" in t or "start on boot" in t or "start with pc" in t:
            if any(w in t for w in ("disable", "turn off", "stop", "don't", "dont", "no")):
                return actions.set_autostart("disable")
            return actions.set_autostart("enable")

        # --- Screenshot ---
        if "screenshot" in t or "screen shot" in t or "capture screen" in t:
            return actions.take_screenshot()

        # --- Lock / power ---
        if "lock" in t:
            return actions.lock_screen()
        if "cancel" in t and ("shut" in t or "restart" in t or "that" in t):
            return actions.power_control("cancel")
        # Through llm_tools, not actions, so these ask before doing — the same
        # question you'd get from the AI brains.
        if ("restart" in t or "reboot" in t) and _means_the_pc(t):
            return llm_tools.power_control("restart")
        if ("shut down" in t or "shutdown" in t or "turn off" in t) and _means_the_pc(t):
            return llm_tools.power_control("shutdown")

        # --- Volume / media ---
        if "volume" in t or "mute" in t:
            if "up" in t or "increase" in t or "raise" in t:
                return actions.control_volume("up")
            if "down" in t or "decrease" in t or "lower" in t:
                return actions.control_volume("down")
            return actions.control_volume("mute")
        if ("pause" in t or ("play" in t and "music" in t) or "resume music" in t
                # "turn off the music" is a media command, not a power one — it
                # gets diverted here rather than shutting the PC down.
                or ("turn off" in t and not _means_the_pc(t))
                or ("stop" in t and ("music" in t or "song" in t or "audio" in t))):
            return actions.media_control("pause")
        if "next track" in t or "next song" in t or "skip" in t:
            return actions.media_control("next")
        if "previous track" in t or "previous song" in t:
            return actions.media_control("previous")

        # --- Wikipedia ---
        m = re.search(r"(?:wikipedia|wiki)(?: for| about)?\s+(.+)", t)
        if m:
            return actions.wikipedia_lookup(m.group(1))

        # --- Close app ---
        m = re.search(r"(?:close|quit|kill|exit)\s+(.+)", t)
        if m:
            return actions.close_app(m.group(1).replace(" app", "").strip())

        # --- Open app / website ---
        m = re.search(r"open\s+(.+)", t)
        if m:
            target = m.group(1).strip()
            if target in actions.SITE_SHORTCUTS or ".com" in target or "website" in target:
                return actions.open_website(target.replace(" website", ""))
            return actions.open_app(target)
        m = re.search(r"(?:go to|launch|start)\s+(.+)", t)
        if m:
            target = m.group(1).strip()
            if target in actions.SITE_SHORTCUTS or ".com" in target:
                return actions.open_website(target)
            return actions.open_app(target)

        # --- Explicit web search ---
        m = re.search(r"(?:search(?: for)?|google|look up)\s+(.+)", t)
        if m:
            return actions.web_search(m.group(1))

        # --- Fallback: search the web so you still get an answer ---
        return actions.web_search(t)
