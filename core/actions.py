"""VONDO's hands — the actual things it can do on your PC.

Every function returns a short string suitable for VONDO to *speak* back.
These are shared by BOTH the free (rule-based) and the Claude (AI) brains,
so PC control behaves identically in either mode.
"""
from __future__ import annotations

import base64
import datetime
import html
import io
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser

import psutil

from core import reminders

# pyautogui is the ONE import in this file that cannot exist in the cloud, and
# a bare `import pyautogui` here took the offline brain down with it.
#
# core/lazy.py defers importing this module precisely so a headless box never
# has to — but only for the functions listed in PC_FUNCTIONS. `brain_free`
# calls get_time, get_date, web_answer, set_reminder and wikipedia_lookup,
# which are pure Python, are NOT in that list, and therefore import this module
# for real. On Render, where pyautogui is not installed, that raised — so the
# brain that exists to answer when every other one has failed was the only
# brain that could not answer at all. Every question, not just desktop ones.
#
# The stub keeps the call sites unchanged and turns a crash into a sentence,
# which is this codebase's rule everywhere else: nothing raises into a
# conversation.
try:
    import pyautogui
except Exception:  # noqa: BLE001
    class _NoDesktop:
        """Stands in for pyautogui where there is no screen to point at."""

        def __getattr__(self, name):
            def refuse(*_args, **_kwargs):
                raise RuntimeError(
                    "this machine has no desktop, so I can't do that here")
            return refuse

    pyautogui = _NoDesktop()  # type: ignore[assignment]

# Friendly name -> Windows launch command. Falls back to the raw name if unknown.
APP_COMMANDS = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "paint": "mspaint",
    "cmd": "cmd",
    "command prompt": "cmd",
    "powershell": "powershell",
    "explorer": "explorer",
    "file explorer": "explorer",
    "task manager": "taskmgr",
    "control panel": "control",
    "settings": "start ms-settings:",
    "spotify": "spotify",
    "vscode": "code",
    "vs code": "code",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
}

# Common site shortcuts for "open youtube" etc.
SITE_SHORTCUTS = {
    "youtube": "https://youtube.com",
    "google": "https://google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "whatsapp": "https://web.whatsapp.com",
    "chatgpt": "https://chat.openai.com",
    "maps": "https://maps.google.com",
    "wikipedia": "https://wikipedia.org",
    "netflix": "https://netflix.com",
    "reddit": "https://reddit.com",
}


def open_app(name: str) -> str:
    """Launch a desktop application by name (e.g. 'chrome', 'notepad')."""
    name = name.strip().lower()
    command = APP_COMMANDS.get(name, name)
    try:
        # shell=True lets Windows resolve app names on PATH and ms-settings: URIs.
        subprocess.Popen(command, shell=True)
        return f"Opening {name}."
    except Exception as exc:  # noqa: BLE001
        return f"I couldn't open {name}. {exc}"


# Friendly name -> Windows process image name, for closing apps with taskkill.
PROCESS_NAMES = {
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "notepad": "notepad.exe",
    "calculator": "CalculatorApp.exe",
    "calc": "CalculatorApp.exe",
    "paint": "mspaint.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
    "spotify": "spotify.exe",
    "vscode": "code.exe",
    "vs code": "code.exe",
    "code": "code.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
}


# ---------------------------------------------------------------------------
# Knowing what's on screen, so "close this" means something.
# ---------------------------------------------------------------------------

# Windows the user never means: our own window, and the empty desktop shell.
_IGNORED_WINDOWS = {"jarvis", "vondo", "program manager", "windows input experience", ""}


def _foreground() -> tuple[str, str]:
    """(window title, process name) of whatever is in front. ('', '') if unknown."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "", ""
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = ""
        try:
            proc = psutil.Process(pid.value).name()
        except Exception:  # noqa: BLE001  (process died, or access denied)
            pass
        return buf.value.strip(), proc
    except Exception:  # noqa: BLE001
        return "", ""


def active_window() -> str:
    """What the user is looking at right now — the app and its window title."""
    title, proc = _foreground()
    if not title and not proc:
        return "I can't tell what's in front at the moment."
    app = proc[:-4] if proc.lower().endswith(".exe") else proc
    if title.lower() in _IGNORED_WINDOWS or not title:
        return f"{app or 'Something'} is in front, with no window title."
    # Most apps title as "document - AppName"; the tail is usually redundant.
    head = title.split(" - ")[0].strip() or title
    return f"{app or 'An app'} is in front, showing {head}."


def top_processes(count: str = "3") -> str:
    """Which programs are using the most memory right now."""
    try:
        n = max(1, min(5, int(str(count).strip() or 3)))
    except ValueError:
        n = 3
    totals: dict[str, float] = {}
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            name = (p.info["name"] or "").lower()
            if not name or name in ("system idle process", "memory compression"):
                continue
            # Browsers run a process per tab — report the app, not 14 fragments.
            totals[name] = totals.get(name, 0.0) + p.info["memory_info"].rss / 1e9
        except Exception:  # noqa: BLE001  (process vanished mid-scan)
            continue
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])[:n]
    if not ranked:
        return "I couldn't read the process list."
    parts = [f"{nm[:-4] if nm.endswith('.exe') else nm} at {gb:.1f} gigabytes"
             for nm, gb in ranked]
    return "Using the most memory: " + ", ".join(parts) + "."


# The ways a person says "the window I'm looking at".
_THIS_WINDOW = {"this", "that", "this window", "that window", "current",
                "current window", "the current window", "it", "this app"}


def is_front_window(name: str) -> bool:
    """True if `name` means "whatever is in front" rather than a named app."""
    return name.strip().lower() in _THIS_WINDOW


def close_active_window() -> str:
    """Close just the window in front — politely.

    Deliberately NOT taskkill: that force-kills every window the app owns and
    throws away unsaved work. This asks the one window to close, exactly as
    clicking its X would, so the app can still prompt you to save.
    """
    title, proc = _foreground()
    if not proc:
        return "I can't tell which window you mean."
    if proc.lower() in ("explorer.exe", "pythonw.exe", "python.exe"):
        # The desktop shell, and Jarvis itself.
        return "I'd rather not close that one. Say the app's name if you mean it."
    label = (title.split(" - ")[0].strip() or proc.removesuffix(".exe"))[:40]
    try:
        import ctypes

        user32 = ctypes.windll.user32
        WM_CLOSE = 0x0010
        if not user32.PostMessageW(user32.GetForegroundWindow(), WM_CLOSE, 0, 0):
            return f"I couldn't close {label}."
    except Exception as exc:  # noqa: BLE001
        return f"I couldn't close {label}. {exc}"
    return f"Closed {label}."


def close_app(name: str) -> str:
    """Close a running desktop application by name (e.g. 'chrome', 'notepad')."""
    name = name.strip().lower()
    # "close this" / "close that window" — whatever is in front.
    if is_front_window(name):
        return close_active_window()
    proc = PROCESS_NAMES.get(name, name if name.endswith(".exe") else f"{name}.exe")
    result = subprocess.run(
        f'taskkill /f /im "{proc}"', shell=True, capture_output=True, text=True
    )
    if result.returncode == 0:
        return f"Closing {name}."
    return f"{name} doesn't appear to be running."


def open_website(target: str) -> str:
    """Open a website. Accepts a shortcut ('youtube'), a domain, or a full URL."""
    target = target.strip().lower()
    if target in SITE_SHORTCUTS:
        url = SITE_SHORTCUTS[target]
        label = target
    elif target.startswith("http"):
        url, label = target, target
    else:
        # Treat "example" or "example.com" as a domain.
        domain = target if "." in target else f"{target}.com"
        url, label = f"https://{domain}", domain
    webbrowser.open(url)
    return f"Opening {label}."


def web_search(query: str) -> str:
    """Open a Google search in the browser for the given query."""
    query = query.strip()
    webbrowser.open(f"https://www.google.com/search?q={query.replace(' ', '+')}")
    return f"Here are the search results for {query}."


# ---------------------------------------------------------------------------
# Researching the web itself, instead of dumping you into a browser tab.
# These return raw text for the AI brain to read and summarise out loud, so
# Jarvis can answer a question rather than just opening Chrome at it.
# ---------------------------------------------------------------------------

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Words too common to prove a search result is on-topic.
_STOPWORDS = {
    "what", "when", "where", "which", "whose", "that", "this", "with", "from",
    "about", "into", "your", "yours", "have", "has", "had", "does", "did",
    "will", "would", "should", "could", "there", "their", "they", "them",
    "current", "currently", "latest", "please", "tell", "give", "know",
}


def _fetch(url: str, timeout: float = 12.0, form: dict | None = None) -> str:
    """GET a URL, or POST it a form. Search engines serve a useless landing page
    to a plain GET, so searches go through as a POST."""
    data = urllib.parse.urlencode(form).encode() if form else None
    headers = {"User-Agent": _UA}
    if form:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _strip_html(raw: str) -> str:
    """Crude but dependency-free HTML -> readable text."""
    raw = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    text = html.unescape(raw)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _wikipedia_summary(query: str) -> str:
    """One-paragraph Wikipedia summary, or '' if there's no clean match.

    Goes through Wikipedia's search first, so a spoken question like "what is the
    capital of Bangladesh" still finds the Dhaka article — turning the question
    straight into a page slug almost never matches.
    """
    try:
        search = ("https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch="
                  + urllib.parse.quote(query.strip()) + "&format=json&srlimit=1")
        hits = json.loads(_fetch(search, 8)).get("query", {}).get("search", [])
        if not hits:
            return ""
        slug = urllib.parse.quote(hits[0]["title"].replace(" ", "_"))
        data = json.loads(_fetch(f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}", 8))
        if data.get("type", "").endswith("disambiguation"):
            return ""
        return (data.get("extract") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _ddg_instant(query: str) -> str:
    """DuckDuckGo's direct answer (definitions, facts), or '' if it has none."""
    try:
        url = ("https://api.duckduckgo.com/?q=" + urllib.parse.quote(query)
               + "&format=json&no_html=1&skip_disambig=1")
        data = json.loads(_fetch(url, 8))
        if data.get("AbstractText"):
            return data["AbstractText"].strip()
        if data.get("Answer"):
            return str(data["Answer"]).strip()
        for topic in data.get("RelatedTopics", [])[:1]:
            if isinstance(topic, dict) and topic.get("Text"):
                return topic["Text"].strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def _ddg_results(query: str, limit: int = 5) -> list[str]:
    """Top result snippets from DuckDuckGo's no-JavaScript HTML endpoint."""
    try:
        page = _fetch("https://html.duckduckgo.com/html/", form={"q": query})
    except Exception:  # noqa: BLE001
        return []
    # Titles and snippets are collected separately and zipped, rather than by
    # matching a block that contains both.
    #
    # The block version anchored on `</td>` — DuckDuckGo's no-JS page used to be
    # a table and is a stack of divs now, so the regex matched exactly nothing
    # and every web question quietly fell through to a Wikipedia guess. Asked
    # for today's news, Jarvis confidently described a newspaper in Chennai.
    #
    # Two flat scans have no containing element to be wrong about, which is the
    # part of someone else's markup most likely to change again.
    titles = [_strip_html(t) for t in
              re.findall(r'(?is)class="result__a"[^>]*>(.*?)</a>', page)]
    snippets = [_strip_html(s) for s in
                re.findall(r'(?is)class="result__snippet"[^>]*>(.*?)</a>', page)]

    out = []
    for index, title in enumerate(titles[: limit * 3]):
        # A result may carry a title and no snippet; that is still a usable
        # line, and pairing by position is right because the page emits them in
        # the same order.
        snippet = snippets[index] if index < len(snippets) else ""
        line = f"{title}. {snippet}".strip(". ").strip()
        # Only keep a result that actually mentions something from the question.
        # Search pages carry ads and unrelated filler, and feeding that to the
        # model makes it wander off into things you never asked about.
        keywords = {w for w in re.findall(r"[a-z]{4,}", query.lower())
                    if w not in _STOPWORDS}
        relevant = not keywords or any(k in line.lower() for k in keywords)
        if line and len(line) > 25 and relevant:
            out.append(line)
        if len(out) >= limit:
            break
    return out


# Where Rohan is, so "the news" means his news. Google News wants these three.
NEWS_LOCALE = (os.getenv("VONDO_NEWS_HL", "en-IN"),
               os.getenv("VONDO_NEWS_GL", "BD"),
               os.getenv("VONDO_NEWS_CEID", "BD:en"))

_NEWS_WORDS = re.compile(
    r"\b(news|headline|headlines|happening|going on|latest|current affairs|"
    r"today.s news|breaking)\b", re.I)

# Words that carry no topic. Boundaries matter: without them this eats the
# letters out of real words, and "bangladesh" becomes "banglade h".
_NEWS_FILLER = re.compile(
    r"\b(brief|tell|give|show|me|my|the|a|an|any|on|of|for|"
    r"today|todays|about|what|whats|is|are|do|you|have|got|some)\b", re.I)


def _news(topic: str = "", limit: int = 6) -> list[str]:
    """Headlines from Google News' RSS feed.

    A feed rather than a scrape, which matters: asked for the news, the search
    path had to guess from page markup and came back with a Wikipedia article
    about a newspaper in Chennai. RSS is a contract — titles in title elements —
    so it does not quietly rot the way someone else's HTML does. Free, no key,
    no account.
    """
    hl, gl, ceid = NEWS_LOCALE
    base = "https://news.google.com/rss"
    if topic.strip():
        url = (f"{base}/search?q={urllib.parse.quote(topic.strip())}"
               f"&hl={hl}&gl={gl}&ceid={ceid}")
    else:
        url = f"{base}?hl={hl}&gl={gl}&ceid={ceid}"
    try:
        feed = _fetch(url)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for block in re.findall(r"(?is)<item>(.*?)</item>", feed)[:limit]:
        title = re.search(r"(?is)<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block)
        source = re.search(r"(?is)<source[^>]*>(.*?)</source>", block)
        if not title:
            continue
        headline = _strip_html(title.group(1)).strip()
        if not headline:
            continue
        # Google appends " - Publisher" to every headline; the source element
        # already carries it, so the suffix is noise read aloud.
        where = _strip_html(source.group(1)).strip() if source else ""
        if where and headline.endswith(f" - {where}"):
            headline = headline[: -len(where) - 3].strip()
        out.append(f"{headline}" + (f" ({where})" if where else ""))
    return out


def news(topic: str = "") -> str:
    """Today's headlines, optionally about something in particular."""
    items = _news(topic)
    if not items:
        return "I couldn't reach the news just now."
    where = f" about {topic.strip()}" if topic.strip() else ""
    header = (f"Today's headlines{where} (summarise these out loud in two or "
              f"three spoken sentences, no URLs, no lists):")
    return header + "\n" + "\n".join(f"- {i}" for i in items)


def web_answer(query: str) -> str:
    """Search the web and return what was found, as text to summarise aloud.

    This is the tool for 'what/who/when/why' questions — Jarvis looks it up and
    tells you the answer instead of opening a browser you'd have to read.
    """
    query = query.strip()
    if not query:
        return "I need something to look up."

    # "Brief me today's news" is not a search — it is a feed, and treating it as
    # a search is how it came back describing a newspaper in Chennai.
    if _NEWS_WORDS.search(query):
        # The word boundaries in _NEWS_FILLER are load-bearing. Without them
        # this stripped letters from the middle of words — "bangladesh" came
        # through as "banglade h" — so the feed was asked for headlines about
        # a topic that does not exist, found none, and fell back to the very
        # search path this branch exists to avoid.
        topic = _NEWS_FILLER.sub(" ", _NEWS_WORDS.sub(" ", query))
        topic = " ".join(topic.split())
        headlines = news(topic)
        if "couldn't reach" not in headlines:
            return headlines

    parts = []
    instant = _ddg_instant(query)
    if instant:
        parts.append(f"Direct answer: {instant}")
    wiki = _wikipedia_summary(query)
    if wiki and wiki[:60] not in instant:
        parts.append(f"Wikipedia: {wiki[:700]}")
    for i, snippet in enumerate(_ddg_results(query), 1):
        parts.append(f"Result {i}: {snippet[:350]}")

    if not parts:
        return (f"I couldn't find anything reliable about {query}. "
                f"Say 'open a search for {query}' if you want the browser instead.")
    findings = "\n".join(parts)[:3500]
    return (f"Web findings for '{query}' (summarise these out loud in one or two "
            f"spoken sentences, no URLs, no lists):\n{findings}")


def read_webpage(url: str) -> str:
    """Fetch one page and return its readable text, for summarising aloud."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        text = _strip_html(_fetch(url, 15))
    except Exception as exc:  # noqa: BLE001
        return f"I couldn't open that page. {exc}"
    if not text:
        return "That page had no readable text."
    return (f"Text of {url} (summarise the key points out loud, briefly):\n"
            f"{text[:4000]}")


def write_code(filename: str, content: str) -> str:
    """Save code (or any text) to a file in the Jarvis workspace and open it.

    Lets you dictate work — "write me a Python script that renames my photos" —
    and end up with a real file on disk instead of code read out loud.
    """
    filename = os.path.basename(filename.strip()) or "untitled.txt"
    workspace = os.path.join(os.path.expanduser("~"), "Documents", "Jarvis Workspace")
    try:
        os.makedirs(workspace, exist_ok=True)
        path = os.path.join(workspace, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as exc:
        return f"I couldn't save that file. {exc}"
    # Show it, so you can see what was written straight away.
    try:
        os.startfile(path)  # noqa: S606  (Windows-only, opens the default editor)
    except Exception:  # noqa: BLE001
        pass
    lines = content.count("\n") + 1
    return f"Saved {filename}, {lines} lines, in your Jarvis Workspace folder."


def wikipedia_lookup(topic: str) -> str:
    """Open the Wikipedia page for a topic."""
    topic = topic.strip()
    webbrowser.open(f"https://en.wikipedia.org/wiki/{topic.replace(' ', '_')}")
    return f"Opening the Wikipedia page for {topic}."


def set_reminder(minutes: str, message: str) -> str:
    """Set a spoken reminder. 'minutes' is how long from now; 'message' is what
    to be reminded about. Jarvis will speak the reminder when the time is up."""
    try:
        mins = float(str(minutes))
    except (TypeError, ValueError):
        mins = 0.0
    reminders.add(mins * 60.0, message)
    if mins <= 0:
        return f"Reminding you now: {message}."
    if mins < 1:
        when = f"{round(mins * 60)} seconds"
    elif mins >= 60 and mins % 60 == 0:
        hrs = int(mins // 60)
        when = f"{hrs} hour" + ("s" if hrs != 1 else "")
    else:
        when = f"{mins:g} minute" + ("s" if mins != 1 else "")
    return f"Okay, I'll remind you to {message} in {when}."


def get_time() -> str:
    """Return the current time."""
    return "It's " + datetime.datetime.now().strftime("%I:%M %p").lstrip("0")


def get_date() -> str:
    """Return today's date."""
    return "Today is " + datetime.datetime.now().strftime("%A, %B %d, %Y")


def system_info() -> str:
    """Report CPU load, memory usage, and battery level."""
    cpu = psutil.cpu_percent(interval=0.4)
    ram = psutil.virtual_memory().percent
    parts = [f"CPU is at {cpu:.0f} percent", f"memory at {ram:.0f} percent"]
    battery = psutil.sensors_battery()
    if battery is not None:
        plugged = "charging" if battery.power_plugged else "on battery"
        parts.append(f"battery at {battery.percent:.0f} percent, {plugged}")
    return ", ".join(parts) + "."


def control_volume(action: str) -> str:
    """Change system volume. action = 'up', 'down', or 'mute'."""
    action = action.strip().lower()
    if action in ("up", "increase", "raise"):
        for _ in range(5):
            pyautogui.press("volumeup")
        return "Volume up."
    if action in ("down", "decrease", "lower"):
        for _ in range(5):
            pyautogui.press("volumedown")
        return "Volume down."
    if action in ("mute", "unmute"):
        pyautogui.press("volumemute")
        return "Toggled mute."
    return "I can turn the volume up, down, or mute it."


def media_control(action: str) -> str:
    """Control media playback. action = 'play', 'pause', 'next', or 'previous'."""
    action = action.strip().lower()
    mapping = {
        "play": "playpause",
        "pause": "playpause",
        "next": "nexttrack",
        "previous": "prevtrack",
        "back": "prevtrack",
    }
    key = mapping.get(action)
    if not key:
        return "I can play, pause, or skip tracks."
    pyautogui.press(key)
    return f"{action.capitalize()}."


def take_screenshot() -> str:
    """Capture the screen and save it to the Pictures folder.

    Needs Pillow, via pyautogui's pyscreeze. That is not automatic — see
    requirements/agent.txt — and when it is missing this fails with a message
    about pyscreeze that says nothing about screenshots.
    """
    folder = os.path.join(os.path.expanduser("~"), "Pictures")
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(folder, f"vondo_screenshot_{stamp}.png")
    pyautogui.screenshot(path)
    return f"Screenshot saved to your Pictures folder."


# ---------------------------------------------------------------------------
# Seeing and driving this machine from somewhere else
#
# Rohan asked for AnyDesk-shaped remote control and chose it knowing the trade:
# a mouse and a keyboard are every action at once, so the allow-list and the
# confirm gates that protect everything else here cannot protect this. What can
# still be true is that it never starts without somebody at the desk agreeing
# (see agent/guard.py) and that it never runs when nobody is watching.
#
# **Frames are PULLED, never pushed.** The viewer asks for the next one when it
# has finished drawing the last, which means: no timer on this machine, no
# stream left running when the phone's screen locks, and a slow link produces
# fewer frames rather than a growing queue. Closing the viewer stops the work
# by simply not asking again — there is nothing to remember to switch off.
# ---------------------------------------------------------------------------

# Sent as base64 inside an ordinary JSON result, so the wire format needed no
# change. It does mean a frame costs a third more than the bytes it carries,
# which is the price of not inventing a second protocol.
SCREEN_MAX_WIDTH = 1280
SCREEN_MIN_WIDTH = 240


def screen_size() -> str:
    """This PC's screen, as "1920x1080"."""
    try:
        width, height = pyautogui.size()
        return f"{int(width)}x{int(height)}"
    except Exception as exc:  # noqa: BLE001
        return f"unknown ({exc})"


def screen_frame(width: int = 900, quality: int = 45) -> str:
    """One JPEG of the whole screen, base64, scaled to `width` pixels across.

    JPEG rather than PNG: a screenshot of a text editor is mostly flat colour
    and PNG would win on size, but a screenshot of anything else — a browser, a
    video, a photo — is three to five times larger as PNG, and this has to be
    sized for the worst case rather than the best.

    Both numbers are clamped here rather than trusted. They arrive from a phone
    over the internet, and a request for a 30,000-pixel-wide frame at quality
    100 is a way to make this machine spend a minute and a gigabyte on one call.
    """
    try:
        from PIL import ImageGrab
    except Exception:  # noqa: BLE001
        # Naming the fix, not just the fault. "No screen grabber installed" is
        # true and useless from a phone in another room.
        return ("error: this PC is missing Pillow, which is what takes the "
                "picture. On the PC run:  .venv\\Scripts\\python -m pip "
                "install pillow   then restart the agent.")

    width = max(SCREEN_MIN_WIDTH, min(SCREEN_MAX_WIDTH, int(width or 900)))
    quality = max(15, min(85, int(quality or 45)))
    try:
        shot = ImageGrab.grab()
        if shot.width > width:
            height = max(1, round(shot.height * width / shot.width))
            # BILINEAR, not LANCZOS. On a 4K desktop the better filter costs
            # more time than the JPEG encode does, every single frame, for a
            # difference nobody can see on a phone.
            shot = shot.resize((width, height), 1)
        if shot.mode != "RGB":
            shot = shot.convert("RGB")
        buffer = io.BytesIO()
        shot.save(buffer, format="JPEG", quality=quality, optimize=False)
    except Exception as exc:  # noqa: BLE001
        return f"error: couldn't capture the screen. ({exc})"
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _to_pixels(x: float, y: float) -> tuple[int, int]:
    """Fractions of the screen to real coordinates.

    The phone sends 0..1 rather than pixels so it never has to know this
    machine's resolution, and so a frame scaled down for the wire still points
    at the right place. Clamped, because a fraction slightly outside the frame
    is a rounding error at the edge of a tap, not a request to leave the screen.
    """
    width, height = pyautogui.size()
    px = int(round(min(1.0, max(0.0, float(x))) * (width - 1)))
    py = int(round(min(1.0, max(0.0, float(y))) * (height - 1)))
    return px, py


def screen_input(kind: str, x: float = 0.0, y: float = 0.0, data: str = "") -> str:
    """Drive this machine: click, scroll, type, or press a key.

    One entry point rather than eight, so the allow-list has one name to reason
    about and the agent has one place to ask permission.

    pyautogui's corner failsafe is deliberately LEFT ON. It is the only physical
    override there is — shove the real mouse into a corner and the next remote
    action raises instead of landing — and for a feature that hands a phone the
    keyboard, an escape hatch that needs no software is worth the rare misfire
    of a genuine click at the very top-left.
    """
    kind = (kind or "").strip().lower()
    try:
        if kind in ("click", "left"):
            pyautogui.click(*_to_pixels(x, y))
        elif kind == "double":
            pyautogui.doubleClick(*_to_pixels(x, y))
        elif kind == "right":
            pyautogui.rightClick(*_to_pixels(x, y))
        elif kind == "middle":
            pyautogui.middleClick(*_to_pixels(x, y))
        elif kind == "move":
            pyautogui.moveTo(*_to_pixels(x, y))
        elif kind == "scroll":
            # y carries the amount here, not a position: a scroll has a
            # direction and a distance and no place on the screen.
            pyautogui.scroll(int(float(y or 0)))
        elif kind == "drag":
            # "x1,y1" in data is where the drag started; x, y is where it ended.
            start = [float(v) for v in (data or "0,0").split(",")[:2]]
            pyautogui.moveTo(*_to_pixels(start[0], start[1]))
            pyautogui.dragTo(*_to_pixels(x, y), duration=0.25, button="left")
        elif kind == "type":
            # interval, not a burst: a few applications drop characters typed
            # faster than a person could, and a dropped character in a password
            # field is a puzzle rather than an error.
            pyautogui.write(str(data or ""), interval=0.01)
        elif kind == "key":
            parts = [p.strip().lower() for p in str(data or "").split("+") if p.strip()]
            if not parts:
                return "No key given."
            if len(parts) == 1:
                pyautogui.press(parts[0])
            else:
                pyautogui.hotkey(*parts)
        else:
            return f"I don't know how to do {kind!r} on this PC."
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        if "FailSafe" in name:
            return ("The mouse is in a screen corner, which is this PC's manual "
                    "override. Move it away and try again.")
        return f"That didn't work on your PC. ({exc})"
    return "ok"


def lock_screen() -> str:
    """Lock the Windows session."""
    subprocess.run("rundll32.exe user32.dll,LockWorkStation", shell=True)
    return "Locking your screen."


# This file lives in core/, but jarvis.state belongs beside the README one level
# up — same reasoning as core.config.PROJECT_DIR, and the same silent breakage
# if the extra dirname is ever dropped.
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STARTUP_DIR = os.path.join(
    os.environ.get("APPDATA", ""),
    "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
)
_LAUNCHER = os.path.join(_STARTUP_DIR, "Jarvis.vbs")
# Remembers whether Jarvis was left on. The boot launcher reads this so it only
# starts with the PC if you did NOT power it off last time.
_STATE_FILE = os.path.join(_PROJECT_DIR, "jarvis.state")


def set_power_state(on: bool) -> None:
    """Remember that Jarvis is currently on (True) or was powered off (False)."""
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            f.write("on" if on else "off")  # no newline: the boot .vbs compares exactly
    except OSError:
        pass


def power_state_on() -> bool:
    """False only if the user explicitly powered Jarvis off last time."""
    try:
        with open(_STATE_FILE, encoding="utf-8") as f:
            return f.read().strip().lower() != "off"
    except OSError:
        return True  # never turned off -> default to on


def autostart_enabled() -> bool:
    """True if the assistant is set to launch automatically at login."""
    return os.path.exists(_LAUNCHER)


def set_autostart(action: str) -> str:
    """Turn boot auto-start on or off. action = 'enable' or 'disable'.

    When enabled, the assistant launches automatically every time the PC boots
    and announces 'System booting'. When disabled, it will not start on its own.
    """
    action = action.strip().lower()
    enable = action in ("enable", "on", "true", "yes", "start")
    if enable:
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pyw):
            pyw = "pythonw"
        script = os.path.join(_PROJECT_DIR, "legacy", "jarvis_gui.py")
        # The launcher runs at every login. It reads jarvis.state first and quietly
        # exits if you powered Jarvis off last time; otherwise it starts it hidden.
        vbs = (
            'Set sh = CreateObject("WScript.Shell")\n'
            'Set fso = CreateObject("Scripting.FileSystemObject")\n'
            'state = "on"\n'
            'On Error Resume Next\n'
            f'If fso.FileExists("{_STATE_FILE}") Then state = LCase(Trim(Replace(Replace(fso.OpenTextFile("{_STATE_FILE}", 1).ReadAll, vbCr, ""), vbLf, "")))\n'
            'On Error GoTo 0\n'
            'If state = "off" Then WScript.Quit\n'
            f'sh.CurrentDirectory = "{_PROJECT_DIR}"\n'
            f'sh.Run """{pyw}"" ""{script}"" --boot", 0, False\n'
        )
        os.makedirs(_STARTUP_DIR, exist_ok=True)
        with open(_LAUNCHER, "w", encoding="utf-8") as f:
            f.write(vbs)
        set_power_state(True)
        return "Auto-start enabled. I'll boot up with your PC unless you power me off first."
    if os.path.exists(_LAUNCHER):
        os.remove(_LAUNCHER)
        return "Auto-start disabled. I won't start on my own anymore."
    return "Auto-start is already off."


def power_control(action: str) -> str:
    """Shut down, restart, or cancel a pending shutdown.

    Shutdown and restart are scheduled with a 30-second delay so they can be
    cancelled by saying 'cancel'. action = 'shutdown', 'restart', or 'cancel'.
    """
    action = action.strip().lower()
    if action == "shutdown":
        subprocess.run("shutdown /s /t 30", shell=True)
        return "Shutting down in 30 seconds. Say cancel to stop."
    if action == "restart":
        subprocess.run("shutdown /r /t 30", shell=True)
        return "Restarting in 30 seconds. Say cancel to stop."
    if action == "cancel":
        subprocess.run("shutdown /a", shell=True)
        return "Cancelled the shutdown."
    return "I can shut down, restart, or cancel."
