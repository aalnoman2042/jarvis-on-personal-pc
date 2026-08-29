"""Shared tool definitions for the LLM brains (Gemini + Groq).

- TOOL_FUNCTIONS: plain Python callables for Gemini's automatic function calling.
- OPENAI_TOOLS:   JSON schemas for Groq's OpenAI-style tool calling.
- DISPATCH:       name -> callable, used to execute Groq tool calls.

All of them just forward to actions.py, so PC control is identical across brains.
Wrappers are defined here (not imported from actions) so the type hints are plain
`str` — which Gemini's schema generator introspects reliably.
"""
import functools

from core.lazy import actions
from core import confirm
from core import mail
from core import memory
from core import phone
from core.memory import contacts
from core.memory import tasks as task_store
from core import reminders
from core import weekly


def _pc_then_phone(on_pc, target: str) -> str:
    """Do it on the desktop; if there is no desktop, do it on the phone.

    "Open YouTube" with the PC asleep used to be answered with "your PC is
    offline" — from a phone perfectly capable of opening YouTube. The desktop is
    still preferred when it is awake, because a big screen is usually what is
    meant; falling back is strictly better than refusing.

    Both the raised and the returned form of "offline" are handled: the agent
    hook raises in some paths and answers politely in others.
    """
    try:
        result = on_pc()
    except Exception:  # noqa: BLE001  (PCOffline, or the agent went mid-call)
        return phone.open_app(target)
    if "offline" in str(result).lower():
        return phone.open_app(target)
    return result


def open_app(name: str) -> str:
    """Open an application. Tries the PC first, then the phone in your hand.

    Use for "open chrome", "open youtube", "open spotify" — anywhere the user
    did not say which device.
    """
    return _pc_then_phone(lambda: actions.open_app(name), name)


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
    """Open a website. Accepts a shortcut ('youtube'), a domain, or a full URL.

    Opens on the PC when it is awake, and on the phone when it is not.
    """
    return _pc_then_phone(lambda: actions.open_website(target), target)


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


def open_on_phone(target: str) -> str:
    """Open an app or website ON THE PHONE — YouTube, WhatsApp, Maps, a URL.

    Use when the PC is offline, or when the user says "on my phone". If the PC
    is awake and they did not say which, open_app is usually what they mean.
    """
    return phone.open_app(target)


def remember_contact(name: str, phone_number: str = "", email: str = "",
                     note: str = "") -> str:
    """Save someone's phone number or email so you can reach them by name later.

    Use whenever the user gives you a number or an address for a person —
    "dad's number is 01712...", "Rifat is on +8801...". Saving it means never
    having to ask twice.
    """
    return contacts.remember(name, phone_number, email, note)


def who_do_i_know() -> str:
    """List the people you have contact details for."""
    people = contacts.everyone()
    if not people:
        return "I don't have anyone's details yet."
    return "You have details for: " + ", ".join(
        p["name"] + (" (phone)" if p["phone"] else "") + (" (email)" if p["email"] else "")
        for p in people) + "."


def call_contact(name: str) -> str:
    """Ring someone you know BY NAME — "call dad", "ring Rifat".

    Looks the number up rather than being told it. Prefer this over
    call_number: guessing digits from a remembered sentence is how a call goes
    to a stranger.
    """
    person = contacts.find(name)
    if not person:
        return (f"I don't have a number for {name}. Tell me it once and I'll "
                f"keep it.")
    if not person["phone"]:
        return f"I know {person['name']} but have no phone number for them."
    contacts.touch(person["id"])
    return phone.call(person["phone"], person["name"])


def message_contact(name: str, text: str = "") -> str:
    """Open WhatsApp to someone you know BY NAME, with the message typed in.

    Does not send it — the last tap stays with you.
    """
    person = contacts.find(name)
    if not person:
        return (f"I don't have a number for {name}. Tell me it once and I'll "
                f"keep it.")
    if not person["phone"]:
        return f"I know {person['name']} but have no phone number for them."
    contacts.touch(person["id"])
    return phone.message(person["phone"], text, person["name"])


def call_number(number: str, who: str = "") -> str:
    """Bring up the phone's dialler with a number ready. Does not dial.

    'number' must be the actual number. If you only have a name, look for it in
    what you remember about the user first, and ask if it is not there.
    """
    return phone.call(number, who)


def message_on_whatsapp(number: str, text: str = "", who: str = "") -> str:
    """Open WhatsApp on a chat with the message typed in. Does not send it.

    'number' must be the actual number, with country code. If you only have a
    name, look in what you remember about the user, and ask if it is not there.
    """
    return phone.message(number, text, who)


def navigate_to(place: str) -> str:
    """Open maps with directions to somewhere."""
    return phone.navigate(place)


def remind(when: str, message: str, warn: str = "") -> str:
    """Put something in the diary: an appointment, a deadline, a task, an exam.

    'when' is when it happens, in the user's own words — "in 20 minutes",
    "tomorrow at 5pm", "18 September", "next Thursday". Pass the phrase through;
    do NOT convert it to a date yourself.

    REPEATING things work too, and the phrase carries them: "every Monday and
    Wednesday at 4pm", "every day at 8am", "weekdays at 9", "every month".
    Pass those through whole — a class timetable is said once, not once a week.
    'message' is what it is, in a few words.
    'warn' is optional and only for things worth knowing about in advance:
    "the day before", "an hour before".

    Use this whenever the user mentions something happening at a time — they do
    not have to say the word "remind".
    """
    return reminders.schedule(when, message, warn)


def check_mail(days: str = "1") -> str:
    """Look at the user's inboxes and say what is worth their attention.

    Use for "any important email", "check my mail", "anything from my
    supervisor", "what's in my inbox". Ranks by who sent it and what it is
    about, and ignores newsletters and automated post. Read-only: it can never
    send, delete or mark anything.
    """
    try:
        window = max(1, min(30, int(str(days).strip() or 1)))
    except (TypeError, ValueError):
        window = 1
    return mail.summary(days=window)


def add_task(text: str, priority: str = "normal", due: str = "") -> str:
    """Put something on the to-do list — work with no fixed time.

    Use for "I need to write the methodology", "remind me to email my
    supervisor", "add finishing the draft to my list". Anything that has to get
    DONE rather than happens AT a time; use `remind` for the latter.

    'priority' is "high", "normal" or "someday". 'due' is an optional deadline
    in the user's own words ("Friday", "the 20th") — pass the phrase through.
    """
    from core import clock
    level = {"high": task_store.HIGH, "someday": task_store.LOW,
             "low": task_store.LOW}.get(priority.strip().lower(), task_store.NORMAL)
    when = 0.0
    if due.strip():
        parsed, _ = clock.parse_when(due)
        when = parsed or 0.0
    if task_store.add(text, level, when) is None:
        return "I couldn't write that down just now."
    said = f"On the list: {text}"
    if when:
        said += f", due {clock.say(when)}"
    return said + "."


def note_commitment(text: str) -> str:
    """Quietly record something the user said they WOULD do, unprompted.

    Use when they mention an intention rather than asking you to track it —
    "I'll finish the draft tonight", "I need to email my supervisor", "I should
    start revising". They did not ask you to remember it; you noticed.

    Say nothing more than a word of acknowledgement afterwards. Announcing that
    you have written it down turns a passing remark into an interrogation.
    Jarvis will ask how it went, once, in a day or two.
    """
    if task_store.add(text, task_store.NORMAL, source="noticed") is None:
        return ""
    return "Noted."


def search_papers(query: str) -> str:
    """Search filed documents — papers, notes, drafts — by meaning.

    Use for "find the paper about X", "what did that paper say about Y",
    "which of my notes mentions Z". It searches what the documents SAY, not
    their filenames, so it works when the words asked for never appear.
    """
    from core import documents
    from core.memory import vectors

    hits = vectors.search(query, limit=4, kinds=("chunk",),
                          floor=vectors.ASKED_FLOOR)
    passages = []
    for hit in hits:
        got = documents.passage(hit["id"])
        if got:
            passages.append(got)
    if not passages:
        filed = documents.all_documents(50)
        if not filed:
            return ("Nothing filed yet. Add a paper or a note and I can search "
                    "inside it.")
        return f"Nothing in the {len(filed)} document(s) I have matches that."

    # The document name every time, because a paragraph with no source is
    # something you have to go and verify before you can use it.
    return " | ".join(
        f"From {p['name']}: {p['text'][:400]}" for p in passages)


def my_documents() -> str:
    """What has been filed. Use for "what papers do I have", "what have I given you"."""
    from core import documents
    filed = documents.all_documents(30)
    if not filed:
        return "Nothing filed yet."
    return "; ".join(
        f"{d['name']} ({d['passages']} passages)" for d in filed) + "."


def my_week() -> str:
    """How the last week actually went — what got done, what did not, what
    was talked about.

    Use for "how was my week", "what did I get done", "how am I doing". It is
    counted from the record, not estimated, so read the figures back as given
    rather than rounding them into a compliment.
    """
    text = weekly.compose()
    return text or "Not enough has happened this week to look back on yet."


def my_tasks() -> str:
    """What is still to do. Use for "what's on my list", "what should I do"."""
    items = task_store.open_tasks()
    if not items:
        return "Nothing on the list."
    return "; ".join(task_store.describe(t) for t in items) + "."


def finish_task(fragment: str) -> str:
    """Tick something off. Use when they say a thing is done or finished."""
    found = task_store.find(fragment)
    if not found:
        return f"I don't have anything open matching '{fragment}'."
    if len(found) > 1:
        return ("More than one of those: "
                + "; ".join(t["text"] for t in found[:4]) + ". Which one?")
    task_store.finish(found[0]["id"])
    return f"Done: {found[0]['text']}."


def check_agenda() -> str:
    """See what is coming up: reminders, deadlines, appointments, events.

    Use for "what's coming up", "what do I have tomorrow", "when is my exam",
    or before answering anything about the user's plans.
    """
    return reminders.upcoming_text()


def change_reminder(fragment: str, new_when: str = "", new_message: str = "") -> str:
    """Move or rename something already in the diary. Use this to EDIT.

    'fragment' is a word or two identifying the existing item ("physics exam").
    'new_when' is the new time in the user's words ("the 20th", "an hour later").
    'new_message' renames it.

    Use this — never cancel and re-create — when the user says a thing already
    in the diary has changed: moved, postponed, brought forward, renamed.
    """
    return reminders.change(fragment, new_when, new_message)


def cancel_reminder(fragment: str) -> str:
    """Drop upcoming reminders matching a word or phrase ('all' clears them)."""
    dropped = reminders.cancel(fragment)
    if not dropped:
        return "Nothing upcoming matched that."
    return f"Cancelled {dropped} item{'s' if dropped != 1 else ''}."


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
    write_code, remember, forget, active_window, top_processes,
    remind, check_agenda, cancel_reminder, change_reminder, check_mail,
    add_task, my_tasks, finish_task, note_commitment, my_week,
    search_papers, my_documents,
    open_on_phone, call_number, message_on_whatsapp, navigate_to,
    remember_contact, who_do_i_know, call_contact, message_contact,
    get_time, get_date, system_info, control_volume, media_control,
    take_screenshot, lock_screen, power_control, set_autostart,
]


def _logged(fn):
    """Record every tool call, so Jarvis can say what it did.

    Wrapping the dispatch table is the honest place for this: it is the point
    Groq, Ollama and Claude all funnel through, so no brain has to remember to
    log. A tool that raises is logged as a failure and the exception re-raised —
    brains have their own handling for that, and swallowing it here would turn a
    broken tool into a silent no-op.

    KNOWN GAP: Gemini is not covered. It uses TOOL_FUNCTIONS directly for
    automatic function calling, and its schema generator introspects each
    callable. functools.wraps keeps __name__ and __annotations__ intact, but a
    generator that reads the signature without following __wrapped__ sees
    `(*args, **kwargs)` and emits a broken schema. Rather than risk a fallback
    brain on an untestable assumption, TOOL_FUNCTIONS stays unwrapped. Close this
    by logging inside the Gemini brain's own call path when it is next touched.
    """
    name = fn.__name__

    @functools.wraps(fn)
    def call(*args, **kwargs):
        detail = ", ".join([str(a) for a in args]
                           + [f"{k}={v}" for k, v in kwargs.items()])
        try:
            # Whether this runs here or on Rohan's PC is decided a layer down,
            # in core.lazy — so this wrapper is only ever about logging.
            result = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001  (log, then let the brain deal with it)
            memory.log_action(name, detail, f"{type(exc).__name__}: {exc}", ok=False)
            raise
        memory.log_action(name, detail, str(result))
        return result

    return call


DISPATCH = {fn.__name__: _logged(fn) for fn in TOOL_FUNCTIONS}


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
    _tool("remind",
          "Put something in the diary: an appointment, deadline, task or event. "
          "Use whenever the user mentions a thing happening at a time.",
          {"when": _STR("When it happens, in their words: 'in 20 minutes', "
                        "'tomorrow at 5pm', '18 September', or a repeating "
                        "pattern like 'every Monday and Wednesday at 4pm'. "
                        "Pass it through whole; do not convert it."),
           "message": _STR("What it is, in a few words"),
           "warn": _STR("Optional, to be told in advance: 'the day before'")},
          ["when", "message"]),
    _tool("open_on_phone",
          "Open an app or website ON THE PHONE (youtube, whatsapp, maps, a URL). "
          "Use when the PC is offline or they said 'on my phone'.",
          {"target": _STR("App name, site, or URL")}, ["target"]),
    _tool("remember_contact",
          "Save someone's phone number or email so you can reach them by name "
          "later. Use whenever the user gives you a number for a person.",
          {"name": _STR("What the user calls them, e.g. 'dad'"),
           "phone_number": _STR("Their number, as given"),
           "email": _STR("Their email, if given"),
           "note": _STR("Anything worth remembering about them")}, ["name"]),
    _tool("who_do_i_know", "List the people you have contact details for."),
    _tool("call_contact",
          "Ring someone BY NAME — 'call dad'. Looks the number up rather than "
          "guessing it. Prefer this over call_number.",
          {"name": _STR("Who to call, e.g. 'dad'")}, ["name"]),
    _tool("message_contact",
          "Open WhatsApp to someone BY NAME with a message typed in. Does not send.",
          {"name": _STR("Who to message"),
           "text": _STR("What to type")}, ["name"]),
    _tool("call_number",
          "Bring up the phone's dialler with a number ready. Does not dial.",
          {"number": _STR("The number, with country code"),
           "who": _STR("Who it is, if known")}, ["number"]),
    _tool("message_on_whatsapp",
          "Open WhatsApp on a chat with the message typed in. Does not send.",
          {"number": _STR("The number, with country code"),
           "text": _STR("What to type"),
           "who": _STR("Who it is, if known")}, ["number"]),
    _tool("navigate_to", "Open maps with directions somewhere.",
          {"place": _STR("Where to go")}, ["place"]),
    _tool("check_mail",
          "Look at the user's email and say what is worth their attention. "
          "Use for 'any important mail', 'check my inbox', 'did X reply'.",
          {"days": _STR("How many days back to look, default 1")}),
    _tool("add_task",
          "Put something on the to-do list — work with no fixed time. Use for "
          "anything that has to get DONE rather than happens AT a time.",
          {"text": _STR("What needs doing"),
           "priority": _STR("high, normal or someday"),
           "due": _STR("Optional deadline in their words, e.g. 'Friday'")},
          ["text"]),
    _tool("note_commitment",
          "Quietly record something the user said they WOULD do, unprompted — "
          "'I'll finish the draft tonight', 'I need to email my supervisor'. "
          "They did not ask you to track it; you noticed. Acknowledge briefly "
          "and do not make a fuss about having written it down.",
          {"text": _STR("What they said they would do, in a few words")}, ["text"]),
    _tool("my_tasks", "What is still to do. Use for 'what's on my list'."),
    _tool("search_papers",
          "Search filed documents \u2014 papers, notes, drafts \u2014 by meaning, not "
          "by filename. Use for 'find the paper about X', 'what did that paper "
          "say about Y', 'which of my notes mentions Z'. Always name the "
          "document a passage came from when you use one.",
          {"query": _STR("What to look for, in their own words")}, ["query"]),
    _tool("my_documents",
          "List the documents that have been filed. Use for 'what papers do I "
          "have', 'what have I given you to read'."),
    _tool("my_week",
          "How the last week actually went — what got finished, what is still "
          "open, what they talked about. Use for 'how was my week', 'what did "
          "I get done', 'how am I doing'. The figures are counted from the "
          "record, so read them back as given."),
    _tool("finish_task", "Tick something off when they say it is done.",
          {"fragment": _STR("A word or two identifying the task")}, ["fragment"]),
    _tool("check_agenda",
          "See what is coming up. Use for 'what's coming up', 'what do I have "
          "tomorrow', 'when is my exam'."),
    _tool("change_reminder",
          "EDIT something already in the diary: move it to a new time or rename "
          "it. Use this rather than cancelling and re-creating when a thing has "
          "moved, been postponed, brought forward or renamed.",
          {"fragment": _STR("A word or two identifying the existing item"),
           "new_when": _STR("The new time in their words, if it moved"),
           "new_message": _STR("A new name, if it was renamed")},
          ["fragment"]),
    _tool("cancel_reminder", "Drop upcoming reminders matching a word ('all' clears them).",
          {"fragment": _STR("Word or phrase to cancel")}, ["fragment"]),
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
    "open_website", "web_open_search", "power_control", "cancel_reminder",
}
OPENAI_TOOLS_LITE = [t for t in OPENAI_TOOLS
                     if t["function"]["name"] not in _LOCAL_SKIP]
